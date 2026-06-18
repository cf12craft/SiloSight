#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil

def main():
    print("SiloSight Executable Builder")
    print("============================")
    
    # 1. Detect site-packages directory of the active python environment using pip show
    ctk_path = None
    try:
        # Run pip show customtkinter
        result = subprocess.run([sys.executable, "-m", "pip", "show", "customtkinter"], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if line.startswith("Location:"):
                location = line.split("Location:")[1].strip()
                ctk_path = os.path.join(location, "customtkinter")
                break
    except Exception as e:
        pass

    if not ctk_path or not os.path.exists(ctk_path):
        print("[!] Error: CustomTkinter must be installed to build the executable.")
        print("    Run: pip install customtkinter")
        sys.exit(1)
        
    print(f"[*] Found CustomTkinter at: {ctk_path}")

    # 2. PyInstaller path separator detection (Windows uses ';', macOS/Linux uses ':')
    sep = ';' if sys.platform.startswith('win') or os.name == 'nt' else ':'
    add_data_arg = f"{ctk_path}{sep}customtkinter/"
    
    # 3. Ensure PyInstaller is installed in the active environment
    try:
        # Check if pyinstaller is available in PATH or python module
        subprocess.run(["pyinstaller", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        pyinstaller_cmd = "pyinstaller"
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("[*] PyInstaller not found in PATH. Checking python module...")
        try:
            subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            pyinstaller_cmd = f"{sys.executable} -m PyInstaller"
        except (FileNotFoundError, subprocess.CalledProcessError):
            print("[*] Installing pyinstaller in the active environment...")
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            pyinstaller_cmd = "pyinstaller"

    # 4. Construct the build command
    # Using Option B: --onefile for a single self-contained executable
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--add-data", add_data_arg,
        "app.py"
    ]
    
    # If using Python module call instead of direct executable
    if pyinstaller_cmd.startswith(sys.executable):
        cmd = [sys.executable, "-m", "PyInstaller"] + cmd[1:]
        
    print(f"[*] Packaging command: {' '.join(cmd)}")
    
    # 5. Run packaging
    try:
        subprocess.run(cmd, check=True)
        print("\n============================")
        print("[*] Packaging completed successfully!")
        
        # Output directory summary
        dist_dir = os.path.join(os.getcwd(), "dist")
        ext = ".exe" if sys.platform.startswith('win') or os.name == 'nt' else ""
        exe_name = f"app{ext}" # PyInstaller names it after the input script by default, i.e., app.exe / app
        dest_name = f"SiloSight{ext}"
        
        src_path = os.path.join(dist_dir, exe_name)
        dest_path = os.path.join(dist_dir, dest_name)
        
        if os.path.exists(src_path):
            if os.path.exists(dest_path):
                os.remove(dest_path)
            os.rename(src_path, dest_path)
            print(f"[*] Standalone executable created: {dest_path}")
        else:
            print(f"[!] Executable generated in 'dist/' directory.")
            
    except subprocess.CalledProcessError as e:
        print(f"\n[!] Packaging failed with error code: {e.returncode}")
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()
