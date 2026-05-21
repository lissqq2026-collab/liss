"""一键启动本项目 Streamlit 服务"""
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

root = Tk()
root.withdraw()

if find_pids():
    messagebox.showinfo("justdo - 启动", f"服务已在运行\n访问 http://localhost:{PORT}")
    root.destroy()
    sys.exit(0)

# 启动 streamlit
subprocess.Popen(
    ['streamlit', 'run', 'app.py'],
    cwd=PROJECT_DIR,
    stdout=open(os.path.join(PROJECT_DIR, 'streamlit.log'), 'w'),
    stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NO_WINDOW
)

# 等几秒确认启动
time.sleep(4)
if find_pids():
    messagebox.showinfo("justdo - 启动", f"服务启动成功\n访问 http://localhost:{PORT}")
else:
    messagebox.showerror("justdo - 启动", "启动失败，请查看 streamlit.log")

root.destroy()
