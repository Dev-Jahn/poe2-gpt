"""Opt-in encrypted decisions, separate from expiring calculation receipts.

Only validated public DTOs enter this store. It has no PoB, cookies or tokens.
The deployment member and verified principal are authenticated data bindings.
"""
from __future__ import annotations
import base64
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Annotated, Literal, TypeVar

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import Field
from .account_store import load_key
from .builds import DTO
from .engine_models import EngineCalculation
from .experiment_models import ExperimentID, ExperimentRequest, ExperimentAudit
from .profiles import Digest
from .observations import ObservationRecord

PlanState = Literal['proposed','accepted','partially_applied','applied','observed','rejected','superseded']
ArtifactKind = Literal['purchase_comparison','currency_portfolio','workflow_trace','guide_evidence','encounter_observation']
ArtifactDTO = TypeVar('ArtifactDTO', bound=DTO)


class DecisionDocument(DTO):
    experiment_id: ExperimentID
    request: ExperimentRequest
    plan_digest: Digest
    audit: ExperimentAudit
    calculation: EngineCalculation
    state: PlanState = 'proposed'
    revision: int = 1
    created_at_epoch: int
    expires_at_epoch: int
    applied_edit_indices: Annotated[list[int], Field(max_length=32)] = Field(default_factory=list)
    observation_ids: Annotated[list[str], Field(max_length=32)] = Field(default_factory=list)
    source_confirmation: Literal['pending_source_confirmation','confirmed_by_source'] = 'pending_source_confirmation'


class WorkflowError(Exception):
    pass


class DecisionStore:
    MAX_RECORDS = 100
    MAX_BYTES = 16 * 1024 * 1024
    MAX_RECORD_BYTES = 512 * 1024

    def __init__(self, member: str, directory: Path | None = None, key_path: Path | None = None):
        self.member=member
        self.memory: OrderedDict[tuple[str,str],DecisionDocument] = OrderedDict()
        self.observations: OrderedDict[tuple[str,str],ObservationRecord] = OrderedDict()
        self.artifacts: OrderedDict[tuple[str,str,str],tuple[int,bytes]] = OrderedDict()
        self.db: sqlite3.Connection | None = None
        self.cipher: AESGCM | None = None
        if directory is not None:
            if key_path is None: raise ValueError('workflow_key_required')
            directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            path=directory/'decisions.sqlite3'
            if path.is_symlink(): raise ValueError('workflow_store_symlink')
            self.cipher=AESGCM(load_key(key_path,create=not path.exists()))
            self.db=sqlite3.connect(path,isolation_level=None)
            os.chmod(path,0o600)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('PRAGMA secure_delete=ON')
            self.db.executescript('''CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS decisions(owner TEXT NOT NULL,id TEXT NOT NULL,expires INTEGER NOT NULL,
                    size INTEGER NOT NULL,revision INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS observations(owner TEXT NOT NULL,id TEXT NOT NULL,expires INTEGER NOT NULL,
                    size INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS artifacts(owner TEXT NOT NULL,kind TEXT NOT NULL,id TEXT NOT NULL,
                    expires INTEGER NOT NULL,size INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(owner,kind,id));''')
            stored=self.db.execute("SELECT value FROM metadata WHERE key='member'").fetchone()
            if stored and stored[0]!=member: raise ValueError('workflow_member_mismatch')
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('member',?)",(member,))

    def owner_key(self, owner: str) -> str:
        return hashlib.sha256((self.member+'\0'+owner).encode()).hexdigest()

    def purge(self) -> None:
        now=int(time.time())
        for key,document in list(self.memory.items()):
            if document.expires_at_epoch<=now: self.memory.pop(key)
        for key,observation in list(self.observations.items()):
            if observation.expires_at_epoch<=now: self.observations.pop(key)
        for artifact_key,(expires,_) in list(self.artifacts.items()):
            if expires<=now: self.artifacts.pop(artifact_key)
        if self.db:
            self.db.execute('DELETE FROM decisions WHERE expires<=?',(now,))
            self.db.execute('DELETE FROM observations WHERE expires<=?',(now,))
            self.db.execute('DELETE FROM artifacts WHERE expires<=?',(now,))

    def save_artifact(self, owner: str, kind: ArtifactKind, identifier: str,
            value: DTO, expires: int, persist: bool) -> None:
        """Internal callers supply a closed DTO; there is no arbitrary JSON tool."""
        self.purge()
        raw=value.model_dump_json().encode()
        if len(raw)>self.MAX_RECORD_BYTES or not int(time.time())<expires<=int(time.time())+90*86400:
            raise WorkflowError('artifact_limit_exceeded')
        key=(self.owner_key(owner),kind,identifier)
        if persist:
            if self.db is None or self.cipher is None: raise WorkflowError('workflow_persistence_unconfigured')
            nonce=secrets.token_bytes(12)
            sealed=nonce+self.cipher.encrypt(nonce,raw,'\0'.join((self.member,'artifacts',*key)).encode())
            self.db.execute('BEGIN IMMEDIATE')
            try:
                count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM artifacts WHERE owner=?',(key[0],)).fetchone()
                if count>=self.MAX_RECORDS or size+len(raw)>self.MAX_BYTES: raise WorkflowError('artifact_quota_exceeded')
                self.db.execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?)',(*key,expires,len(raw),sealed))
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise
        else:
            if key in self.artifacts: raise WorkflowError('artifact_already_exists')
            size=sum(len(payload) for _,payload in self.artifacts.values())
            while self.artifacts and (len(self.artifacts)>=self.MAX_RECORDS or size+len(raw)>self.MAX_BYTES):
                _,(_,payload)=self.artifacts.popitem(last=False);size-=len(payload)
            self.artifacts[key]=(expires,raw)

    def get_artifact(self, owner: str, kind: ArtifactKind, identifier: str, model: type[ArtifactDTO]) -> ArtifactDTO:
        self.purge()
        key=(self.owner_key(owner),kind,identifier)
        if key in self.artifacts: return model.model_validate_json(self.artifacts[key][1])
        if self.db is not None and self.cipher is not None:
            row=self.db.execute('SELECT payload FROM artifacts WHERE owner=? AND kind=? AND id=?',key).fetchone()
            if row:
                raw=row[0]
                try:
                    payload=self.cipher.decrypt(raw[:12],raw[12:],'\0'.join((self.member,'artifacts',*key)).encode())
                    return model.model_validate_json(payload)
                except Exception: raise WorkflowError('artifact_integrity_failure') from None
        raise WorkflowError('artifact_expired_or_unavailable')

    def delete_artifact(self, owner: str, kind: ArtifactKind, identifier: str) -> None:
        key=(self.owner_key(owner),kind,identifier)
        self.artifacts.pop(key,None)
        if self.db: self.db.execute('DELETE FROM artifacts WHERE owner=? AND kind=? AND id=?',key)

    def update_portfolio(self, owner: str, identifier: str, value: DTO, expected_revision: int) -> None:
        self.update_mutable_artifact(owner,'currency_portfolio',identifier,value,expected_revision)

    def update_mutable_artifact(self, owner: str, kind: Literal['currency_portfolio','workflow_trace'],
            identifier: str, value: DTO, expected_revision: int) -> None:
        """Closed internal mutable artifacts; immutable decision receipts stay immutable."""
        self.purge()
        key=(self.owner_key(owner),kind,identifier)
        conflict='portfolio_revision_conflict' if kind=='currency_portfolio' else 'workflow_trace_revision_conflict'
        raw=value.model_dump_json().encode()
        if len(raw)>self.MAX_RECORD_BYTES: raise WorkflowError('artifact_limit_exceeded')
        if key in self.artifacts:
            expires,previous=self.artifacts[key]
            current=type(value).model_validate_json(previous)
            if current.model_dump()['revision']!=expected_revision: raise WorkflowError(conflict)
            size=sum(len(payload) for _,payload in self.artifacts.values())-len(previous)+len(raw)
            if size>self.MAX_BYTES: raise WorkflowError('artifact_quota_exceeded')
            self.artifacts[key]=(expires,raw)
            return
        if self.db is None or self.cipher is None: raise WorkflowError('artifact_expired_or_unavailable')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT payload,size FROM artifacts WHERE owner=? AND kind=? AND id=?',key).fetchone()
            if not row: raise WorkflowError('artifact_expired_or_unavailable')
            old,size=row
            aad='\0'.join((self.member,'artifacts',*key)).encode()
            current=type(value).model_validate_json(self.cipher.decrypt(old[:12],old[12:],aad))
            if current.model_dump()['revision']!=expected_revision: raise WorkflowError(conflict)
            total=self.db.execute('SELECT COALESCE(SUM(size),0) FROM artifacts WHERE owner=?',(key[0],)).fetchone()[0]
            if total-size+len(raw)>self.MAX_BYTES: raise WorkflowError('artifact_quota_exceeded')
            nonce=secrets.token_bytes(12)
            sealed=nonce+self.cipher.encrypt(nonce,raw,aad)
            self.db.execute('UPDATE artifacts SET payload=?,size=? WHERE owner=? AND kind=? AND id=?',(sealed,len(raw),*key))
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def save_observation(self, owner: str, record: ObservationRecord) -> None:
        self.purge()
        key=(self.owner_key(owner),record.observation_id)
        raw=record.model_dump_json().encode()
        if len(raw)>8192: raise WorkflowError('observation_too_large')
        if record.request.persist_observation:
            if self.db is None or self.cipher is None: raise WorkflowError('workflow_persistence_unconfigured')
            count=self.db.execute('SELECT COUNT(*) FROM observations WHERE owner=?',(key[0],)).fetchone()[0]
            if count>=self.MAX_RECORDS: raise WorkflowError('observation_quota_exceeded')
            nonce=secrets.token_bytes(12)
            aad='\0'.join((self.member,'observations',*key)).encode()
            sealed=nonce+self.cipher.encrypt(nonce,raw,aad)
            self.db.execute('INSERT INTO observations VALUES (?,?,?,?,?)',(*key,record.expires_at_epoch,len(raw),sealed))
        else:
            while len(self.observations)>=self.MAX_RECORDS:self.observations.popitem(last=False)
            self.observations[key]=record.model_copy(deep=True)

    def get_observation(self, owner: str, identifier: str) -> ObservationRecord:
        self.purge()
        key=(self.owner_key(owner),identifier)
        if key in self.observations:return self.observations[key].model_copy(deep=True)
        if self.db is not None and self.cipher is not None:
            row=self.db.execute('SELECT payload FROM observations WHERE owner=? AND id=?',key).fetchone()
            if row:
                raw=row[0];aad='\0'.join((self.member,'observations',*key)).encode()
                try:return ObservationRecord.model_validate_json(self.cipher.decrypt(raw[:12],raw[12:],aad))
                except Exception:raise WorkflowError('observation_integrity_failure') from None
        raise WorkflowError('observation_expired_or_unavailable')

    def delete_observation(self, owner: str, identifier: str) -> None:
        key=(self.owner_key(owner),identifier)
        self.observations.pop(key,None)
        if self.db:self.db.execute('DELETE FROM observations WHERE owner=? AND id=?',key)

    def save(self, owner: str, document: DecisionDocument, expected_revision: int | None = None) -> None:
        raw=document.model_dump_json().encode()
        if len(raw)>self.MAX_RECORD_BYTES: raise WorkflowError('decision_too_large')
        self.purge()
        key=(self.owner_key(owner),document.experiment_id)
        if expected_revision is not None:
            current=self.get(owner,document.experiment_id)
            if current.revision!=expected_revision: raise WorkflowError('plan_revision_conflict')
        if document.request.persist_decision:
            if self.db is None or self.cipher is None: raise WorkflowError('workflow_persistence_unconfigured')
            count,size=self.db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM decisions WHERE owner=?',(key[0],)).fetchone()
            old=self.db.execute('SELECT size FROM decisions WHERE owner=? AND id=?',key).fetchone()
            if (not old and count>=self.MAX_RECORDS) or size-(old[0] if old else 0)+len(raw)>self.MAX_BYTES:
                raise WorkflowError('decision_quota_exceeded')
            nonce=secrets.token_bytes(12)
            aad='\0'.join((self.member,*key)).encode()
            sealed=nonce+self.cipher.encrypt(nonce,raw,aad)
            if expected_revision is None:
                self.db.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?)',(*key,document.expires_at_epoch,len(raw),document.revision,sealed))
            else:
                changed=self.db.execute('UPDATE decisions SET expires=?,size=?,revision=?,payload=? WHERE owner=? AND id=? AND revision=?',
                    (document.expires_at_epoch,len(raw),document.revision,sealed,*key,expected_revision)).rowcount
                if changed!=1: raise WorkflowError('plan_revision_conflict')
        else:
            size=sum(len(value.model_dump_json().encode()) for value in self.memory.values())
            while self.memory and (len(self.memory)>=self.MAX_RECORDS or size+len(raw)>self.MAX_BYTES):
                _,old=self.memory.popitem(last=False);size-=len(old.model_dump_json().encode())
            self.memory[key]=document.model_copy(deep=True)

    def get(self, owner: str, identifier: str) -> DecisionDocument:
        self.purge()
        key=(self.owner_key(owner),identifier)
        if key in self.memory: return self.memory[key].model_copy(deep=True)
        if self.db is not None and self.cipher is not None:
            row=self.db.execute('SELECT payload FROM decisions WHERE owner=? AND id=?',key).fetchone()
            if row:
                raw=row[0];aad='\0'.join((self.member,*key)).encode()
                try:
                    return DecisionDocument.model_validate_json(self.cipher.decrypt(raw[:12],raw[12:],aad))
                except Exception:
                    raise WorkflowError('decision_integrity_failure') from None
        raise WorkflowError('decision_expired_or_unavailable')

    def delete(self, owner: str, identifier: str) -> None:
        key=(self.owner_key(owner),identifier)
        self.memory.pop(key,None)
        if self.db: self.db.execute('DELETE FROM decisions WHERE owner=? AND id=?',key)

    def close(self) -> None:
        if self.db: self.db.close()
