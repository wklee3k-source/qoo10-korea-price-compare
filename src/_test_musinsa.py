import subprocess, sys
proc = subprocess.run(
    [sys.executable, "musinsa_name_corrector.py", "닥터지 레드 블레미쉬", "", "닥터지"],
    capture_output=True, text=True, timeout=30,
)
print("STDOUT:", proc.stdout[:1500])
print("STDERR:", proc.stderr[:500])
