"""Windows QA probe. Requires psutil, Pillow and pywin32 in the test interpreter."""
import argparse
import gc
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine as E


def low_memory(path):
    import win32api
    import win32job
    import psutil
    fixture = path / "memory.json"
    fixture.write_bytes(b'{"FFlagDebugSkyGray":"' + b'x' * (10 * 1024**2) + b'"}')
    job = win32job.CreateJobObject(None, f'Firetier-QA-{os.getpid()}')
    info = win32job.QueryInformationJobObject(job,win32job.JobObjectExtendedLimitInformation)
    cap = psutil.Process().memory_info().private + 8 * 1024**2
    info["ProcessMemoryLimit"] = cap
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
    win32job.SetInformationJobObject(job,win32job.JobObjectExtendedLimitInformation,info)
    win32job.AssignProcessToJobObject(job,win32api.GetCurrentProcess())
    result = E.import_profile_file(fixture)
    assert result.kind == "out-of-memory" and result.profile is None, result.kind
    print(json.dumps({"limit_bytes":cap,"result":result.kind}))


def probe(work):
    import psutil
    import tkinter as tk
    from PIL import Image
    import firetier as F
    from unittest.mock import patch
    report = {}
    store = E.ProfileStore(work)
    raw = json.dumps({"replacements":[{"assetId":1000000+i} for i in range(10000)]})
    start = time.perf_counter()
    for i in range(30):
        item = E.import_profile_text(raw,"Assets")
        assert item.profile.unsupported
        store.save(item.profile)
    profiles = store.list()
    assert len({p.id for p in profiles}) == 30
    assert len(profiles[-1].source["original"]["replacements"]) == 10000
    report["30_imports_10000_asset_rows_each_including_reload_s"] = round(time.perf_counter()-start,3)
    del profiles, store
    gc.collect()
    big = work / "large.json"
    with big.open("wb") as f:
        f.write(b'{"ignored":"' + b'x'*(18*1024**2)+b'"}')
    start=time.perf_counter()
    assert E.import_profile_file(big).kind == "unknown"
    report["18_MiB_valid_unrecognized_json_ms"] = round((time.perf_counter()-start)*1000)
    with big.open("wb") as f:
        f.truncate(E.MAX_JSON_BYTES+1)
    assert E.import_profile_file(big).kind == "too-large"
    png = work/"large.png"
    Image.new("RGB",(8192,8192),color="navy").save(png)
    assert E.import_profile_file(png).kind == "unreadable"
    report["8192x8192_png"] = "rejected by JSON importer; no image decoder in app"
    report["over_20_MiB"] = "rejected"
    cp = subprocess.run([sys.executable,__file__,str(work),"--low-memory"],capture_output=True,text=True,timeout=20,check=True)
    report["windows_job_memory_test"] = json.loads(cp.stdout)
    root=tk.Tk()
    app=F.App(root,work/"gui",work/"no-install")
    root.update()
    app.nb.select(2)
    root.update()
    ids=["preset-rivals-notex","preset-balanced","preset-rivals-fps"]
    for i in ids:
        app.select_profile(i)
        root.update()
    proc=psutil.Process()
    gc.collect()
    mem=[proc.memory_info().rss]
    photos=[len(root.tk.call("image","names"))]
    timings=[]
    for i in range(240):
        tick=time.perf_counter()
        app.select_profile(ids[i%3])
        root.update()
        timings.append((time.perf_counter()-tick)*1000)
        if i%60==59:
            gc.collect()
            mem.append(proc.memory_info().rss)
            photos.append(len(root.tk.call("image","names")))
    report["240_warm_preview_switches_ms"]={"median":round(statistics.median(timings),2),
        "p95":round(sorted(timings)[227],2),"max":round(max(timings),2)}
    report["working_set_MiB_at_0_60_120_180_240"]=[round(x/1024**2,2) for x in mem]
    report["tk_image_counts"]=photos
    assert len(set(photos)) == 1
    def slow(*args):
        time.sleep(.45)
        return [E.Check("ok","fixture","finished")]
    with patch("engine.run_diagnostics",side_effect=slow):
        app.run_diag()
        ticks=0
        while app.diag_pending:
            root.update()
            ticks+=1
            time.sleep(.01)
        assert ticks>=5
        report["event_loop_ticks_during_450ms_diagnostic"]=ticks
    app.on_close()
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("path",type=Path)
    parser.add_argument("--low-memory",action="store_true")
    args=parser.parse_args()
    if args.low_memory:
        low_memory(args.path)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            data=probe(Path(tmp))
        args.path.write_text(json.dumps(data,indent=2))
        print(json.dumps(data,indent=2))

