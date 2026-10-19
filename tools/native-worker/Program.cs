using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;

// Runs in a short-lived child process, never inside the editor or game.
// Export signatures and serializer flags come from the installed Story Editor
// and OsirisBinding implementation. The caller checks the inspected DLL hash.
if(args.Length!=5) throw new ArgumentException("dll sha256 input.div output.osi log.txt");
Native.SetErrorMode(3);
var dll=Path.GetFullPath(args[0]);
if(!Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(dll))).Equals(args[1],StringComparison.OrdinalIgnoreCase))
    throw new InvalidOperationException("The native compiler differs from the inspected build.");
var input=Path.GetFullPath(args[2]); var output=Path.GetFullPath(args[3]); var log=Path.GetFullPath(args[4]);
if(input==output || input==log || output==log) throw new ArgumentException("Input, output and log must be different files.");
var library=NativeLibrary.Load(dll);
Native.ExceptionHandler handler=null!;
if(Environment.GetEnvironmentVariable("OSIRIS_WORKER_TRACE")=="1") {
    handler=p=>{
        var record=Marshal.ReadIntPtr(p);
        if(Marshal.ReadInt32(record)==unchecked((int)0xc0000005)) {
            var address=Marshal.ReadIntPtr(record,16);
            Console.Error.WriteLine($"Native access violation at compiler RVA 0x{address.ToInt64()-library.ToInt64():X}; address=0x{address:X}");
            var context=Marshal.ReadIntPtr(p,8);
            var stack=(IntPtr)Marshal.ReadInt64(context,152);
            Console.Error.WriteLine($"return RVA 0x{Marshal.ReadInt64(stack)-library.ToInt64():X}");
        }
        return 0;
    };
    Native.AddVectoredExceptionHandler(1,handler);
}
T Export<T>(string name) where T:Delegate=>Marshal.GetDelegateForFunctionPointer<T>(NativeLibrary.GetExport(library,name));
var create=Export<Native.Create>("?CreateOsirisObject@COsiris@@SAXPEAVIMemoryAllocator@@@Z");
var get=Export<Native.Get>("?GetOsirisObject@COsiris@@SAPEAV1@XZ");
var register=Export<Native.Register>("?RegisterDIVFunctions@COsiris@@QEAAXPEAUTOsirisInitFunction@@@Z");
var destroy=Export<Native.Void>("?DeleteOsirisObject@COsiris@@SAXXZ");
var openLog=Export<Native.OpenLog>("?OpenLogFile@COsiris@@QEAA_NPEB_WH@Z");
var closeLog=Export<Native.ThisVoid>("?CloseLogFile@COsiris@@QEAAXXZ");
var compile=Export<Native.Compile>("?Compile@COsiris@@QEAA_NPEB_W0@Z");
var ioCtor=Export<Native.IoCtor>("??0COsiSmartBufIOFile@@QEAA@PEB_W_N@Z");
var ioDtor=Export<Native.ThisVoid>("??1COsiSmartBufIOFile@@UEAA@XZ");
var bufCtor=Export<Native.BufCtor>("??0COsiSmartBuf@@QEAA@PEAVCOsiSmartBufIO@@_N_KE@Z");
var bufDtor=Export<Native.ThisVoid>("??1COsiSmartBuf@@QEAA@XZ");
var save=Export<Native.Save>("?Save@COsiris@@QEAA_NAEAVCOsiSmartBuf@@_N1@Z");
using var allocator=new Allocator();
using var callbacks=new Callbacks();
IntPtr osi=IntPtr.Zero,io=IntPtr.Zero,buf=IntPtr.Zero;
bool compiled=false,saved=false;
void Phase(string text) { if(Environment.GetEnvironmentVariable("OSIRIS_WORKER_TRACE")=="1")Console.Error.WriteLine(text); }
try {
    Phase("create");
    create(allocator.Instance); osi=get();
    if(osi==IntPtr.Zero) throw new InvalidOperationException("Native compiler construction failed");
    register(osi,callbacks.Table);
    Phase("open log");
    if(!openLog(osi,log,18)) throw new IOException("Cannot open compiler log");
    Phase("compile");
    compiled=compile(osi,input,"r+");
    compiled=compiled&&callbacks.AssertionFailures==0;
    Phase("compile returned: "+compiled);
    if(compiled) {
        io=Marshal.AllocHGlobal(256); buf=Marshal.AllocHGlobal(256);
        Phase("IO constructor");ioCtor(io,output,false);
        Phase("buffer constructor");bufCtor(buf,io,false,1024,0);
        Phase("save");saved=save(osi,buf,false,true);Phase("save returned: "+saved);
        bufDtor(buf); Marshal.FreeHGlobal(buf);buf=IntPtr.Zero;
        ioDtor(io); Marshal.FreeHGlobal(io);io=IntPtr.Zero;
    }
    closeLog(osi);
    Console.WriteLine(JsonSerializer.Serialize(new {compiled,saved,output,log,allocations=allocator.TotalAllocations,peakBytes=allocator.PeakBytes}));
} finally {
    if(buf!=IntPtr.Zero) {bufDtor(buf);Marshal.FreeHGlobal(buf);}
    if(io!=IntPtr.Zero) {ioDtor(io);Marshal.FreeHGlobal(io);}
    if(osi!=IntPtr.Zero) {Phase("destroy");destroy();}
    GC.KeepAlive(allocator);
    GC.KeepAlive(callbacks);
    GC.KeepAlive(handler);
}
return compiled&&saved?0:1;

sealed class Callbacks:IDisposable {
    readonly Delegate[] roots;
    public IntPtr Table {get;}
    public int AssertionFailures {get;private set;}
    public Callbacks() {
        Native.HostCall unavailable=(id,parameters)=>{Environment.FailFast("Compiler attempted a game call");return 0;};
        Native.HostError error=message=>Console.Error.WriteLine("Osiris: "+Marshal.PtrToStringUTF8(message));
        Native.HostAssert assertion=(condition,message,flag)=>{
            if(condition==0) {AssertionFailures++;Console.Error.WriteLine("Osiris assertion: "+Marshal.PtrToStringUTF8(message));}
        };
        roots=new Delegate[]{unavailable,unavailable,unavailable,error,assertion};
        Table=Marshal.AllocHGlobal(roots.Length*8);
        for(int i=0;i<roots.Length;i++)Marshal.WriteIntPtr(Table,i*8,Marshal.GetFunctionPointerForDelegate(roots[i]));
    }
    public void Dispose()=>Marshal.FreeHGlobal(Table);
}

sealed class Allocator:IDisposable {
    readonly Dictionary<IntPtr,ulong> owned=new();
    readonly Native.Allocate allocate; readonly Native.Free free;
    readonly Native.ThisVoid enter,leave;
    readonly IntPtr vtable;
    public IntPtr Instance {get;}
    public long TotalAllocations {get;private set;}
    public ulong PeakBytes {get;private set;}
    ulong bytes;
    public Allocator() {
        // The inspected x64 ABI has allocation/free at slots 0/1, with a group
        // argument, and parameterless scope hooks at 2/3. This isolated worker
        // is single threaded, so the scope hooks require no host synchronisation.
        allocate=Alloc;free=Release;enter=_=>{};leave=_=>{};
        vtable=Marshal.AllocHGlobal(32);Instance=Marshal.AllocHGlobal(8);
        Delegate[] methods={allocate,free,enter,leave};
        for(int i=0;i<methods.Length;i++)Marshal.WriteIntPtr(vtable,i*8,Marshal.GetFunctionPointerForDelegate(methods[i]));
        Marshal.WriteIntPtr(Instance,vtable);
    }
    IntPtr Alloc(IntPtr self,ulong size,ulong group) {
        var p=Native.HeapAlloc(Native.GetProcessHeap(),8,(UIntPtr)Math.Max(size,1));
        if(p==IntPtr.Zero) Environment.FailFast("Native compiler allocation failed");
        owned.Add(p,size);bytes+=size;PeakBytes=Math.Max(bytes,PeakBytes);TotalAllocations++;
        return p;
    }
    void Release(IntPtr self,IntPtr p,ulong group) {
        if(p==IntPtr.Zero)return;
        if(!owned.Remove(p,out var size))Environment.FailFast("Native compiler freed an unknown allocation");
        bytes-=size;Native.HeapFree(Native.GetProcessHeap(),0,p);
    }
    public void Dispose() {
        foreach(var p in owned.Keys)Native.HeapFree(Native.GetProcessHeap(),0,p);
        Marshal.FreeHGlobal(Instance);Marshal.FreeHGlobal(vtable);
    }
}

static class Native {
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate int ExceptionHandler(IntPtr pointers);
    [DllImport("kernel32.dll")]public static extern IntPtr AddVectoredExceptionHandler(uint first,ExceptionHandler handler);
    [DllImport("kernel32.dll")]public static extern uint SetErrorMode(uint mode);
    [DllImport("kernel32.dll")]public static extern IntPtr GetProcessHeap();
    [DllImport("kernel32.dll")]public static extern IntPtr HeapAlloc(IntPtr heap,uint flags,UIntPtr size);
    [DllImport("kernel32.dll")][return:MarshalAs(UnmanagedType.Bool)]public static extern bool HeapFree(IntPtr heap,uint flags,IntPtr block);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate void Create(IntPtr allocator);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate IntPtr Get();
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate void Register(IntPtr self,IntPtr callbacks);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate byte HostCall(uint id,IntPtr parameters);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate void HostError(IntPtr message);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate void HostAssert(int condition,IntPtr message,byte flag);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate void Void();
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate void ThisVoid(IntPtr self);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate IntPtr Allocate(IntPtr self,ulong size,ulong group);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]public delegate void Free(IntPtr self,IntPtr pointer,ulong group);
    [UnmanagedFunctionPointer(CallingConvention.Winapi,CharSet=CharSet.Unicode)][return:MarshalAs(UnmanagedType.I1)]
    public delegate bool OpenLog(IntPtr self,string path,int flags);
    [UnmanagedFunctionPointer(CallingConvention.Winapi,CharSet=CharSet.Unicode)][return:MarshalAs(UnmanagedType.I1)]
    public delegate bool Compile(IntPtr self,string input,string mode);
    [UnmanagedFunctionPointer(CallingConvention.Winapi,CharSet=CharSet.Unicode)]
    public delegate IntPtr IoCtor(IntPtr self,string path,[MarshalAs(UnmanagedType.I1)]bool reading);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    public delegate IntPtr BufCtor(IntPtr self,IntPtr io,[MarshalAs(UnmanagedType.I1)]bool reading,ulong size,byte flags);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)][return:MarshalAs(UnmanagedType.I1)]
    public delegate bool Save(IntPtr self,IntPtr buffer,[MarshalAs(UnmanagedType.I1)]bool savegame,[MarshalAs(UnmanagedType.I1)]bool story);
}
