import ctypes
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import audio_analysis as a
import ser_experiment as ser

class Counters(ctypes.Structure):
    _fields_=[('cb',ctypes.c_ulong),('PageFaultCount',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in
        ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
         'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]

def peak_mb():
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
    ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(counters),counters.cb)
    return round(counters.PeakWorkingSetSize/1024/1024,1)

def run():
    started=time.monotonic(); ser.get_model(); load_ms=round((time.monotonic()-started)*1000,1)
    pcm,_=a._decode(Path(__file__).parent/'chinese-fixture.wav',time.monotonic()+15)
    results=[ser.predict(pcm[:seconds*16000]) for seconds in [3,8,8]]
    report={'fixture':'Windows SAPI synthetic Chinese (not a human emotion dataset)',
            'load_ms':load_ms,'peak_working_set_mb':peak_mb(),'results':results,
            'production_enabled':False,'reason':'No labeled real Mandarin interview audio; probabilities uncalibrated'}
    path=Path(__file__).resolve().parents[1]/'docs/ser-benchmark.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))

if __name__=='__main__': run()
