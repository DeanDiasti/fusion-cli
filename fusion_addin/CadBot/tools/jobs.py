"""Session-scoped tracking for Fusion cloud futures; no worker touches adsk."""
import time
import uuid
import adsk.core

_jobs={}


def register(future,operation):
    if len(_jobs)>=32:
        raise RuntimeError('Job tracking capacity reached; inspect or forget completed jobs first')
    key=uuid.uuid4().hex
    _jobs[key]={'future':future,'operation':operation,'started':time.monotonic()}
    return {'job':key,'status':'pending','cancel_supported':False}


def inspect(args):
    key=args['job']
    if key not in _jobs: raise ValueError('Unknown job or Fusion session changed')
    job=_jobs[key];future=job['future']
    state=future.uploadState
    states=adsk.core.UploadStates
    status='completed' if state==states.UploadFinished else 'failed' if state==states.UploadFailed else 'pending'
    result={'job':key,'operation':job['operation'],'status':status,'cancel_supported':False,
            'elapsed_seconds':round(time.monotonic()-job['started'],2)}
    if status=='completed':
        from .admin import file_info
        result['file']=file_info(future.dataFile)
    elif status=='pending' and result['elapsed_seconds']>300:
        result['warning']='Cloud operation exceeds five minutes. Fusion may still complete it; do not retry blindly.'
    return result


def list_jobs(args):
    return {'jobs':[inspect({'job':key}) for key in _jobs]}


def cancel(args):
    result=inspect(args)
    return {**result,'cancelled':False,
            'blocker':'Installed Fusion DataFileFuture exposes status and result only; cancellation is unavailable.'}


def forget(args):
    result=inspect(args)
    if result['status']=='pending': raise ValueError('Cannot forget an operation still running')
    del _jobs[args['job']]
    return {'forgotten':args['job']}
