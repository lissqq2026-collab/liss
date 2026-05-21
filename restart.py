"""重启本项目 Streamlit 服务"""
import subprocess
import os
import sys
import time
from tkinter import Tk, messagebox

PORT = 8501
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

def find_pids():
    result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
    pids = []
    for line in result.stdout.splitlines():
        if f':{PORT}' in line and 'LISTENING' in line:
            pids.append(line.split()[-1])
    return pids

def kill(pid):
    subprocess.run(['taskkill', '/PID', pid, '/F'], capture_output=True)

root = Tk()
root.withdraw()

# 停止
for pid in find_pids():
    kill(pid)
time.sleep(1)

# 启动
subprocess.Popen(
    ['streamlit', 'run', 'app.py'],
    cwd=PROJECT_DIR,
    stdout=open(os.path.join(PROJECT_DIR, 'streamlit.log'), 'w'),
    stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NO_WINDOW
)

time.sleep(4)
if find_pids():
    messagebox.showinfo("justdo - 重启", f"服务重启成功\n访问 http://localhost:{PORT}")
else:
    messagebox.showerror("justdo - 重启", "重启失败，请查看 streamlit.log")

root.destroy()
