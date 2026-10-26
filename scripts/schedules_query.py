"""Query official public ONE/COSCO schedules through the shared service API."""
import argparse
import json
from pathlib import Path
from personal_wecom import ClientError, read_session, request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', default=str(Path.home()/'.config/personal-wecom/session.json'))
    parser.add_argument('--origin')
    parser.add_argument('--destination')
    parser.add_argument('--origin-country')
    parser.add_argument('--destination-country')
    parser.add_argument('--from', dest='departure_from')
    parser.add_argument('--until', dest='departure_until')
    parser.add_argument('--carrier', action='append', choices=['ONE','COSCO'], dest='carriers')
    parser.add_argument('--routing',choices=['any','direct','transshipment'])
    parser.add_argument('--origin-id',action='append',default=[],metavar='CARRIER=ID')
    parser.add_argument('--destination-id',action='append',default=[],metavar='CARRIER=ID')
    args = parser.parse_args()
    payload = {k:v for k,v in vars(args).items() if v is not None and k not in {'session','origin_id','destination_id'}}
    for side in ('origin','destination'):
        ids={}
        for entry in getattr(args,side+'_id'):
            carrier,sep,value=entry.partition('=')
            if not sep or carrier not in {'ONE','COSCO'} or not value or carrier in ids:
                parser.error('Location ID must be a unique ONE=ID or COSCO=ID pair')
            ids[carrier]=value
        if ids: payload[side+'_ids']=ids
    try:
        session=read_session(Path(args.session).expanduser())
        result=request(session['base_url'],'/schedules/query',method='POST',data=payload,credential=session['credential'])
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if result['status']=='unavailable' else 0
    except (ClientError,OSError,ValueError,KeyError):
        print(json.dumps({'status':'unavailable','message':'请求未完成，请检查登录会话、权限和连接。未自动重试。'},ensure_ascii=False))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
