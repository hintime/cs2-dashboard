"""
Silent update runner — runs every 10 min via Windows Task Scheduler
Keeps price_history.json growing for charts & scoring
"""
import os, subprocess, time

DATA_DIR = r'C:\Users\Lenovo\WorkBuddy\Claw\cs2-dashboard'
PYTHON = r'C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe'
PYTHONW = r'C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\pythonw.exe'

# 从本地文件读取 ECO 私钥
eco_key_path = os.path.join(DATA_DIR, 'eco_private_key.txt')
if os.path.exists(eco_key_path):
    with open(eco_key_path) as f:
        os.environ.setdefault('ECO_PRIVATE_KEY_B64', f.read().strip())

os.environ.setdefault('STEAMDT_KEY', '6fdc816dc6c2469588f34050cc32a9e4')
os.environ.setdefault('GH_TOKEN', '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')
os.environ.setdefault('GIT_TERMINAL_PROMPT', '0')
os.environ.setdefault('GIT_ASKPASS', 'echo')

env = os.environ.copy()
env.pop('GIT_TERMINAL_PROMPT', None)

# 静默日志文件
LOG_FILE = os.path.join(DATA_DIR, 'silent_update.log')
def log(msg):
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}\n')

def run_py(args):
    result = subprocess.run([PYTHONW, os.path.join(DATA_DIR, args[0])] + args[1:],
        cwd=DATA_DIR, capture_output=True, text=True, timeout=600,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
    if result.stdout:
        log(f'[update.py] {result.stdout.strip()[-500:]}')
    if result.stderr:
        log(f'[update.py ERR] {result.stderr.strip()[-500:]}')
    return result

def run_git(cmd):
    result = subprocess.run(['git', '-c', 'http.sslBackend=openssl', '-c', 'http.sslVerify=false'] + cmd,
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
