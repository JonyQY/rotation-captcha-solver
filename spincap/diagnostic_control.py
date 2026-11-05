"""Local file mailbox for a diagnostic process independent of terminal stdin.

No network listener or browser credentials. An interrupted request is never
replayed: its running marker remains for inspection.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
from time import sleep, time
import uuid


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    temp.write_text(json.dumps(value, ensure_ascii=True), encoding='utf-8')
    temp.replace(path)


@contextmanager
def control_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'worker.lock').open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            import msvcrt
        except ImportError:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        yield
        # Closing the descriptor releases the OS lock, including after a crash.


def consume_one(directory, handler):
    directory = Path(directory)
    requests = directory/'requests'
    requests.mkdir(parents=True, exist_ok=True)
    for request_path in sorted(requests.glob('*.json')):
        request_id = request_path.stem
        if len(request_id) != 32 or any(c not in '0123456789abcdef' for c in request_id):
            continue
        result_path = directory/'responses'/request_path.name
        running_path = directory/'running'/request_path.name
        if result_path.exists() or running_path.exists():
            request_path.unlink()
            continue
        running_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.replace(running_path)
        try:
            request = json.loads(running_path.read_text(encoding='utf-8'))
            if request.pop('expires_at', 0) < time():
                result = {'type':'error', 'error_type':'ExpiredCommand'}
            else:
                result = handler(request)
        except Exception as error:
            result = {'type':'error', 'error_type':type(error).__name__}
        write_json(result_path, result)
        running_path.unlink()
        return result
    return None


def submit(directory, action, confirmed=False, timeout=45):
    directory = Path(directory)
    request_id = uuid.uuid4().hex
    result_path = directory/'responses'/f'{request_id}.json'
    write_json(directory/'requests'/f'{request_id}.json',
               {'action':action, 'confirmed':confirmed, 'expires_at':time()+timeout})
    deadline = time()+timeout
    while time() < deadline:
        if result_path.exists():
            return json.loads(result_path.read_text(encoding='utf-8'))
        sleep(0.1)
    raise TimeoutError('Diagnostic command timed out; do not automatically repeat a test.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-dir', type=Path, required=True)
    parser.add_argument('action', choices=('status','prepare','test_once','stop'))
    parser.add_argument('--confirmed', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(submit(args.control_dir, args.action, args.confirmed), ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
