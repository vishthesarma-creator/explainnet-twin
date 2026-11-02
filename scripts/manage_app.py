"""Start/check/stop only recorded ordinary-user services; no laboratory mutations."""
import json
import sys

from explainnet.app_launcher import main

if __name__=='__main__':
    try:
        main()
    except (ValueError,RuntimeError,OSError) as exc:
        print(json.dumps({'status':'failed','error':str(exc),'automatically_retried':False}),file=sys.stderr)
        raise SystemExit(1) from None
