# Dhara Windows Job Object host.
#
# Electron spawns this script and keeps its stdin open. The script owns a Job Object created with
# JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. Every process assigned to the job is terminated automatically
# when this host exits — which happens when Electron exits or is force-killed (stdin closes), or when
# the host itself is killed (its job handle closes).
#
# Protocol (one command per line on stdin, one reply per line on stdout):
#   (startup)        -> READY
#   ADD <pid>        -> OK <pid> | ERR <pid> <win32-error>
#   DETACH           -> OK DETACH      (clears kill-on-close so processes survive the host)
#   ATTACH           -> OK ATTACH      (re-enables kill-on-close)
#   PING             -> PONG
#   EXIT / stdin EOF -> host exits (kills job members unless DETACHed)

$ErrorActionPreference = 'Stop'

$source = @"
using System;
using System.Runtime.InteropServices;

public static class DharaJob
{
    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct BASIC_LIMITS
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct EXTENDED_LIMITS
    {
        public BASIC_LIMITS BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CreateJobObject(IntPtr attrs, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint size);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr OpenProcess(uint access, bool inherit, int pid);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool CloseHandle(IntPtr handle);

    const int JobObjectExtendedLimitInformation = 9;
    const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;
    const uint PROCESS_SET_QUOTA = 0x0100;
    const uint PROCESS_TERMINATE = 0x0001;

    public static IntPtr Create()
    {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new Exception("CreateJobObject failed: " + Marshal.GetLastWin32Error());
        if (!SetKill(job, true)) throw new Exception("SetInformationJobObject failed: " + Marshal.GetLastWin32Error());
        return job;
    }

    public static bool SetKill(IntPtr job, bool kill)
    {
        EXTENDED_LIMITS info = new EXTENDED_LIMITS();
        info.BasicLimitInformation.LimitFlags = kill ? JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE : 0;
        int size = Marshal.SizeOf(typeof(EXTENDED_LIMITS));
        IntPtr ptr = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(info, ptr, false);
            return SetInformationJobObject(job, JobObjectExtendedLimitInformation, ptr, (uint)size);
        }
        finally
        {
            Marshal.FreeHGlobal(ptr);
        }
    }

    // Returns 0 on success, otherwise the Win32 error code.
    public static int Assign(IntPtr job, int pid)
    {
        IntPtr proc = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, false, pid);
        if (proc == IntPtr.Zero) return Marshal.GetLastWin32Error();
        try
        {
            if (!AssignProcessToJobObject(job, proc)) return Marshal.GetLastWin32Error();
            return 0;
        }
        finally
        {
            CloseHandle(proc);
        }
    }
}
"@

function Reply([string]$text) {
    [Console]::Out.WriteLine($text)
    [Console]::Out.Flush()
}

try {
    Add-Type -TypeDefinition $source -Language CSharp
    $job = [DharaJob]::Create()
} catch {
    Reply ("FATAL " + $_.Exception.Message)
    exit 2
}

Reply 'READY'

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    $parts = $line.Trim() -split '\s+'
    $cmd = $parts[0].ToUpperInvariant()
    switch ($cmd) {
        'ADD' {
            $procId = 0
            if ($parts.Length -lt 2 -or -not [int]::TryParse($parts[1], [ref]$procId)) {
                Reply 'ERR 0 bad-pid'
                break
            }
            $code = [DharaJob]::Assign($job, $procId)
            if ($code -eq 0) { Reply "OK $procId" } else { Reply "ERR $procId $code" }
        }
        'DETACH' {
            [void][DharaJob]::SetKill($job, $false)
            Reply 'OK DETACH'
        }
        'ATTACH' {
            [void][DharaJob]::SetKill($job, $true)
            Reply 'OK ATTACH'
        }
        'PING' { Reply 'PONG' }
        'EXIT' { exit 0 }
        default { }
    }
}
