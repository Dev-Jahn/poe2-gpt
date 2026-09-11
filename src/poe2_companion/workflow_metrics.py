"""Opt-in context-local timing only; no arguments, identity or external text."""
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import time
import json
import math
from typing import Iterator, Literal, Callable, Awaitable, ParamSpec, TypeVar
from functools import wraps

Phase = Literal['queue','worker_round_trip','worker_execution','parse','network','rate_wait','validation']


@dataclass
class Measurements:
    milliseconds: dict[str,float] = field(default_factory=dict)
    counts: Counter[str] = field(default_factory=Counter)


CURRENT: ContextVar[Measurements | None] = ContextVar('poe2_workflow_measurements',default=None)
P = ParamSpec('P')
T = TypeVar('T')


def measured(phase: Phase) -> Callable[[Callable[P,Awaitable[T]]],Callable[P,Awaitable[T]]]:
    def decorate(function: Callable[P,Awaitable[T]]) -> Callable[P,Awaitable[T]]:
        @wraps(function)
        async def invoke(*args: P.args, **kwargs: P.kwargs) -> T:
            with span(phase): return await function(*args,**kwargs)
        return invoke
    return decorate


@contextmanager
def span(phase: Phase) -> Iterator[None]:
    value=CURRENT.get()
    start=time.monotonic()
    try: yield
    finally:
        if value is not None:
            value.milliseconds[phase]=value.milliseconds.get(phase,0.0)+(time.monotonic()-start)*1000


def count(name: Literal['cache_hit','cache_miss','queue_rejected','upstream_request']) -> None:
    value=CURRENT.get()
    if value is not None: value.counts[name]+=1


def observe_header() -> dict[str,str]:
    return {'x-poe2-observe':'1'} if CURRENT.get() is not None else {}


def absorb_worker_header(header: str | None) -> None:
    value=CURRENT.get()
    if value is None or header is None or len(header)>2048: return
    try:
        data=json.loads(header)
        if not isinstance(data,dict): return
        for key,amount in data.get('milliseconds',{}).items():
            if key in {'queue','worker_execution','parse','validation'} and type(amount) in {int,float} and math.isfinite(amount) and 0<=amount<=120000:
                value.milliseconds[key]=value.milliseconds.get(key,0.0)+amount
        for key,number in data.get('counts',{}).items():
            if key in {'cache_hit','cache_miss','queue_rejected'} and type(number) is int and 0<=number<=100:
                value.counts[key]+=number
    except (ValueError,TypeError,AttributeError): return
