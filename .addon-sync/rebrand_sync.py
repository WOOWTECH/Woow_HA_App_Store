#!/usr/bin/env python3
"""Copy only public addon download resources into the private rebrand checkout."""
import argparse,hashlib,json,pathlib,re,subprocess

def render(store,target,revision):
    store=pathlib.Path(store);target=pathlib.Path(target)
    catalog=json.loads((store/'.addon-sync/catalog.json').read_text())
    canonical=json.dumps(catalog['components'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    expected='sha256:'+hashlib.sha256(canonical).hexdigest()
    if catalog.get('schema')!=1 or catalog.get('catalog_id')!=expected:raise ValueError('Invalid Store catalog')
    for folder in [target/'release',target/'release/addons']:
        if folder.is_symlink():raise ValueError('Refuse symlink destination')
    dest=target/'release/addons';dest.mkdir(parents=True,exist_ok=True)
    for name in ['catalog.json','download_addon.py','README.md','sync-state.json']:
        if (dest/name).is_symlink():raise ValueError('Refuse symlink output')
    rows=[]
    for cid,e in sorted(catalog['components'].items()):
        name=e['name'].replace('|','\\|').replace('\n',' ')
        rows.append(f"| `{cid}` | {name} | {e['version']} | {', '.join(e['architectures'])} | {e['delivery']} |")
    text='''# HA addon Local Download

此目錄由 `WOOWTECH/Woow_HA_App_Store` 的同步工作流程維護。
它是可下載的 addon 目錄與工具，**不是已安裝設備清單，也不會自動升級設備**。

```sh
python3 download_addon.py --catalog catalog.json --list
python3 download_addon.py woow_ha_pi_agent --catalog catalog.json --destination ./local-addons --arch amd64
```

核對後將新的 addon 目錄放到 HAOS `/addons/`，重新載入 Supervisor 商店，再手動安裝。
也可明確使用 `--destination /addons` 下載新項目；工具拒絕覆寫既有目錄。
既有安裝的升級、設定與資料遷移須另行處理，**不要為了更新而直接解除安裝**。

- 只需 Python 3 標準函式庫；下載來源為公開 WOOWTECH repo 的固定 commit。
- 檢查目錄、封存檔與 manifest 雜湊；拒絕路徑穿越、連結及特殊檔案。
- 發布映像包裝為固定 digest 的 local Dockerfile；這是映像封裝，**不是重新編譯原始碼**。
- 無發布映像的項目在安裝時 local build；清單只證明來源/套件檢查，**不保證 Docker 建置或實機健康**。
- `--source-build` 只接受具有完整獨立建置 context 的項目。
- 新下載項目一律 manual boot；不安裝、不啟動 DHCP/MQTT，也不更動帳號或認證。
- 開發/測試通道、已封存或淘汰項目不自動加入此穩定清單。
- 通知與同步為最終一致；GitHub 排程可能延遲。兩邊以相同 catalog ID/來源 SHA 辨識版本。
- 信任 GitHub repo 寫入權限及 HTTPS；此版未實作獨立密碼學簽章驗證。

## 可下載版本

| ID | 名稱 | 版本 | 架構 | 安裝內容 |
|---|---|---|---|---|
'''+ '\n'.join(rows)+'\n'
    outputs={'catalog.json':(store/'.addon-sync/catalog.json').read_bytes(),'download_addon.py':(store/'.addon-sync/download_addon.py').read_bytes(),'README.md':text.encode()}
    try:old=json.loads((dest/'sync-state.json').read_text())
    except (OSError,ValueError):old={}
    # Unchanged published resources keep the Store commit that produced them, so an
    # unrelated Store commit never causes a private-repository commit.
    if old.get('catalog_id')==expected and re.fullmatch(r'[0-9a-f]{40}',str(old.get('app_store_commit',''))) and all((dest/n).is_file() and (dest/n).read_bytes()==b for n,b in outputs.items()):
        revision=old['app_store_commit']
    for name,data in outputs.items():(dest/name).write_bytes(data)
    state={'schema':1,'app_store_repository':'WOOWTECH/Woow_HA_App_Store','app_store_commit':revision,'catalog_id':expected,'component_count':len(catalog['components'])}
    (dest/'sync-state.json').write_text(json.dumps(state,indent=2)+'\n')
    return state

def commit_scope(root,allowed,message,push=False):
    root=str(root)
    def git(*args,**kw):return subprocess.run(['git','-C',root,*args],check=True,**kw)
    git('add','-A')
    files=subprocess.check_output(['git','-C',root,'diff','--cached','--name-only','-z']).decode().split('\0')
    files=[f for f in files if f]
    for f in files:
        if not any(f==a or f.startswith(a+'/') for a in allowed):raise ValueError('Refuse write outside synchronization scope: '+f)
    if not files:return False
    git('config','user.name','github-actions[bot]');git('config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    git('commit','-m',message)
    if push:git('push','origin','HEAD:main')
    return True

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['store-commit','rebrand']);p.add_argument('--store',default='.');p.add_argument('--target');p.add_argument('--push',action='store_true');a=p.parse_args()
    if a.mode=='store-commit':
        registry=json.loads((pathlib.Path(a.store)/'.addon-sync/registry.json').read_text())
        allowed={c['store_path'] for p in registry['providers'].values() for c in p['components']}
        allowed.add('.addon-sync/catalog.json')
        print('Store changed:',commit_scope(a.store,allowed,'chore(addons): consume validated source notifications',a.push))
    else:
        revision=subprocess.check_output(['git','-C',a.store,'rev-parse','HEAD'],text=True).strip()
        state=render(a.store,a.target,revision)
        print('Rebrand changed:',commit_scope(a.target,{'release/addons'},'chore(addons): synchronize local download catalog',a.push))
        print(json.dumps(state))

if __name__=='__main__':main()
