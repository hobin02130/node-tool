import os
import shutil
import subprocess
import sys
import platform
import zipfile
import glob

# ---------------------------------------------------------
# Configuration Area
# ---------------------------------------------------------
PROJECT_NAME = "NodeTool"  # Generated exe/binary name (used for zip filename)
SPEC_FILE = "node_tool.spec"  # PyInstaller spec file
DIST_DIR = "dist"
BUILD_DIR = "build"
RELEASE_DIR = "release"  # Final release directory

# External assets to copy to the release directory
# Format: (Source Path, Destination Folder Name)
EXTERNAL_ASSETS = [
    # (Source, Destination: empty string means root)
    ("app/subscription/nodes", "nodes"),  # Copy nodes folder
    ("db_config.json", ""),      # Copy db config if exists
    ("app.db", ""),              # Copy database if exists (optional)
]

def clean_dirs():
    """Clean up temporary build directories"""
    print(f"[Clean] Cleaning up old build files...", flush=True)
    for d in [DIST_DIR, BUILD_DIR, RELEASE_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)

def run_pyinstaller():
    """Run PyInstaller"""
    print(f"[Build] Starting PyInstaller build ({platform.system()})...", flush=True)
    
    # Check if spec file exists
    if not os.path.exists(SPEC_FILE):
        print(f"[Error] Error: {SPEC_FILE} not found. Please generate the spec file first.", flush=True)
        sys.exit(1)

    # Run PyInstaller command
    try:
        # 🟢 [修改] 添加 --noupx 参数，防止 Windows Defender 误删生成的 exe
        subprocess.check_call([sys.executable, "-m", "PyInstaller", SPEC_FILE, "--clean", "-y", "--noupx"])
        print("[Success] PyInstaller build completed", flush=True)
    except subprocess.CalledProcessError:
        print("[Error] PyInstaller build failed", flush=True)
        sys.exit(1)

def organize_release():
    """Organize release folder: copy exe and external assets"""
    print(f"[Organize] Organizing release files to '{RELEASE_DIR}'...", flush=True)
    
    if not os.path.exists(RELEASE_DIR):
        os.makedirs(RELEASE_DIR)

    # 1. Determine the executable name automatically
    system_name = platform.system()
    
    found_exe = None
    if system_name == "Windows":
        # 在 Windows 上找 .exe 文件
        exe_files = glob.glob(os.path.join(DIST_DIR, "*.exe"))
        if exe_files:
            found_exe = exe_files[0] # 取第一个找到的 exe
    else:
        # 在 Linux/Mac 上，通常是没有后缀的二进制文件
        # 我们查找 dist 下的所有文件，排除掉文件夹
        potential_files = [f for f in os.listdir(DIST_DIR) if os.path.isfile(os.path.join(DIST_DIR, f))]
        if potential_files:
            found_exe = os.path.join(DIST_DIR, potential_files[0])

    if not found_exe or not os.path.exists(found_exe):
        print(f"[Error] Error: No executable file found in {DIST_DIR}", flush=True)
        # 列出 dist 目录内容方便调试
        if os.path.exists(DIST_DIR):
            print(f"Content of {DIST_DIR}: {os.listdir(DIST_DIR)}", flush=True)
        sys.exit(1)
        
    exe_filename = os.path.basename(found_exe)
    print(f"   -> Found generated executable: {exe_filename}", flush=True)

    # 2. Move executable
    dst_exe = os.path.join(RELEASE_DIR, exe_filename)
    shutil.copy2(found_exe, dst_exe)
    print(f"   -> Copied executable to release folder", flush=True)

    # 3. Copy external assets (nodes folder, etc.)
    for src, dst_folder in EXTERNAL_ASSETS:
        # Check if source exists
        if not os.path.exists(src):
            print(f"   [Warning] Warning: Asset not found, skipping: {src}", flush=True)
            continue

        final_dst = os.path.join(RELEASE_DIR, dst_folder)
        
        if os.path.isdir(src):
            # If it's a directory
            if os.path.exists(final_dst):
                shutil.rmtree(final_dst)
            shutil.copytree(src, final_dst)
            print(f"   -> Copied folder: {src} -> {dst_folder}/", flush=True)
        else:
            # If it's a file
            shutil.copy2(src, final_dst)
            print(f"   -> Copied file: {src}", flush=True)

    # 4. Set execution permissions for Linux
    if system_name != "Windows":
        os.chmod(dst_exe, 0o755)

def make_archive():
    """Create archive for release"""
    print("[Compress] Creating archive...", flush=True)
    
    # Architecture name (e.g., amd64, arm64, win32)
    arch = platform.machine().lower()
    os_name = platform.system().lower()
    zip_name = f"{PROJECT_NAME}_{os_name}_{arch}.zip"
    
    # Change directory to make the archive path clean
    shutil.make_archive(os.path.join(".", zip_name.replace('.zip', '')), 'zip', RELEASE_DIR)
    
    print(f"[Done] Build successful! File located at: {os.path.abspath(zip_name)}", flush=True)

if __name__ == "__main__":
    clean_dirs()
    run_pyinstaller()
    organize_release()
    make_archive()
