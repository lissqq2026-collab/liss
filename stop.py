"""关闭本项目 Streamlit 服务"""
import subprocess
import os
import sys
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

pids = find_pids()
if not pids:
    messagebox.showinfo("justdo - 关闭", "未发现运行中的服务")
else:
    for pid in pids:
        kill(pid)
    messagebox.showinfo("justdo - 关闭", f"服务已关闭 (终止 {len(pids)} 个进程)")

root.destroy()
