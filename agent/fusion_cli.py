"""Terminal interface to the shared typed Fusion command catalog."""
import json
import shlex
import sys
from bridge_cli import call, runtime_status
from command_catalog import load


def main(argv):
    argv = list(argv)
    json_output = bool(argv and argv[0] == '--json')
    if json_output:
        argv.pop(0)
    if argv == ['doctor']:
        result, status = runtime_status()
    elif argv == ['--version']:
        build = load('build')
        result, status = {'build': build.BUILD, 'protocol': build.PROTOCOL}, 200
    else:
        result, status = call('fusion', {'command': shlex.join(['fusion', *argv])})
    if not json_output and ('help' in result or 'commands' in result):
        if 'help' in result:
            print(result['help'], end='')
        else:
            print(result['usage'])
            print('\n'.join('  fusion ' + command for command in result['commands']))
            print('\nLocal commands: fusion doctor, fusion --version. Use --json before the command for JSON help.')
    else:
        print(json.dumps(result, indent=2))
    return 2 if status == 400 else 1 if status >= 400 or 'error' in result else 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print('Interrupted. An executing Fusion operation may still finish; inspect before retrying.', file=sys.stderr)
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(0)
