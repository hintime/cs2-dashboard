"""
Silent update runner — runs every 10 min via Windows Task Scheduler
Keeps price_history.json growing for charts & scoring
"""
import os, subprocess, sys, time

# ★ 2026-10-09 废弃：本机 updater_daemon 已于 2026-09-21 禁用（updater_daemon.py 内 sys.exit），
#   且本文件所用 Bearer 认证已被 update.py 的 Basic 认证取代（见下方 run_git 注释，勿在服务器用）。
#   保留仅作历史参考——运行时直接退出，避免用错误路径/旧认证把冻结的本机数据误推上远端。
#   如需临时恢复：将 DEPRECATED 置 False（并先恢复 daemon）即可。
DEPRECATED = True
if DEPRECATED:
    sys.stderr.write('[DEPRECATED] run_update.py 已废弃（本机 daemon 自 2026-09-21 禁用，'
                     'Bearer 认证已废弃），直接退出。请勿使用。\n')
    sys.exit(0)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = r'C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe'
PYTHONW = r'C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\pythonw.exe'

# 从本地文件读取 ECO 私钥
eco_key_path = os.path.join(DATA_DIR, 'eco_private_key.txt')
if os.path.exists(eco_key_path):
    with open(eco_key_path) as f:
        os.environ.setdefault('ECO_PRIVATE_KEY_B64', f.read().strip())

if os.path.exists(os.path.join(DATA_DIR, 'local_keys.env')):
    for _l in open(os.path.join(DATA_DIR, 'local_keys.env'), encoding='utf-8'):
        _l = _l.strip()
        if _l and not _l.startswith('#') and '=' in _l:
            _k, _v = _l.split('=', 1)
            os.environ.setdefault(_k.strip(), _v.strip())
# 从 git_credential.txt 读取 GitHub Token（不提交到 git）
_token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.git', '..', 'git_credential.txt')
if not os.path.exists(_token_path):
    _token_path = os.path.join(DATA_DIR, 'git_credential.txt')
if os.path.exists(_token_path):
    with open(_token_path) as f:
        GITHUB_TOKEN = f.read().strip()
else:
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '') or os.environ.get('GH_TOKEN', '')
os.environ.setdefault('GIT_TERMINAL_PROMPT', '0')
os.environ.setdefault('GIT_ASKPASS', 'echo')

env = os.environ.copy()
env.pop('GIT_TERMINAL_PROMPT', None)
env['SCHEDULED_RUN'] = '1'  # 告诉 update.py 这是定时任务，限制 SteamDT 批次数
env['PYTHONIOENCODING'] = 'utf-8'  # 防止GBK编码错误导致推送跳过
env['PYTHONLEGACYWINDOWSSTDIO'] = 'utf-8'

# 静默日志文件
LOG_FILE = os.path.join(DATA_DIR, 'silent_update.log')
def log(msg):
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}\n')

def run_py(args):
    result = subprocess.run([PYTHONW, os.path.join(DATA_DIR, args[0])] + args[1:],
        cwd=DATA_DIR, capture_output=True, text=True, timeout=600, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
    if result.stdout:
        log(f'[update.py] {result.stdout.strip()[-500:]}')
    if result.stderr:
        log(f'[update.py ERR] {result.stderr.strip()[-500:]}')
    return result

def run_git(cmd):
    # 用 token 认证
    # ⚠ 注：本文件是**旧版 Windows 启动器**，认证用的是 Bearer —— 但 GitHub 的 git 传输
    #   只认 Basic（`x-access-token:<token>`），Bearer 会 rc=128 失败。核心链路已改走
    #   update.py 的 _git_auth_args()，本文件保留仅为历史参考，勿在服务器上使用。
    full_cmd = ['git']
    if sys.platform == 'win32':
        full_cmd += ['-c', 'http.sslBackend=openssl']
    full_cmd += ['-c', 'http.sslVerify=false']
    if cmd[0] in ('push', 'pull', 'fetch'):
        full_cmd += ['-c', f'http.extraHeader=Authorization: Bearer {GITHUB_TOKEN}']
    result = subprocess.run(full_cmd + cmd,
        cwd=DATA_DIR, capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
    if result.stderr and 'warning' not in result.stderr.lower():
        log(f'[git] {result.stderr.strip()[-300:]}')
    return result

# 1. 同步代码
run_git(['stash'])
run_git(['pull', '--rebase', 'origin', 'main'])

# 2. 运行数据更新（积累 price_history + 生成推荐）
run_py(['update.py', 'all'])

# 3. 推送数据到 GitHub（由 update.py 内部的 push_all 完成）
