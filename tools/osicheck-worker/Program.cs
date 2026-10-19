using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text;
using System.Text.RegularExpressions;

// All game-derived data and compiler outputs are written to the calling build folder.
// LSLib remains an external dependency supplied by the user's OsiCheck installation.
var standardOutput=Console.Out;
using var compilerOutput=new StringWriter();
Console.SetOut(compilerOutput);
try {
    var request=JsonSerializer.Deserialize<Request>(File.ReadAllText(args.Single()),new JsonSerializerOptions{PropertyNameCaseInsensitive=true})!;
    var libraries=Path.GetFullPath(request.LibraryDir);
    AssemblyLoadContext.Default.Resolving+=(context,name)=>{
        var file=Path.Combine(libraries,name.Name+".dll");
        return File.Exists(file)?context.LoadFromAssemblyPath(file):null;
    };
    AssemblyLoadContext.Default.ResolvingUnmanagedDll+=(_,name)=>{
        var file=Path.Combine(libraries,name.EndsWith(".dll")?name:name+".dll");
        return File.Exists(file)?NativeLibrary.Load(file):IntPtr.Zero;
    };
    var assembly=AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(libraries,"LSLib.dll"));
    dynamic New(string name,params object[] values)=>Activator.CreateInstance(assembly.GetType(name,true)!,values)!;
    var output=Path.GetFullPath(request.OutputDir); Directory.CreateDirectory(output);
    var overlay=Path.Combine(output,"inputs");
    var project=Path.GetFullPath(request.ProjectPath);
    var module=Path.GetFileName(project);
    var mods=request.BaseMods.Where(name=>!name.Equals(module,StringComparison.OrdinalIgnoreCase)).Append(module).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    var paths=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
    var hashes=new SortedDictionary<string,string>(StringComparer.Ordinal);
    foreach(var mod in mods) {
        if(string.IsNullOrWhiteSpace(mod) || mod!=Path.GetFileName(mod) || mod is "." or "..") throw new ArgumentException("Invalid dependency module name: "+mod);
        if(request.PackageOnly && mod!=module) continue;
        var original=mod==module?project:Path.Combine(request.GameDataPath,"Mods",mod);
        var source=Path.Combine(original,"Story","RawFiles");
        var target=Path.Combine(overlay,"Mods",mod);
        if(!Directory.Exists(source)) continue;
        Directory.CreateDirectory(target);
        var meta=Path.Combine(original,"meta.lsx");
        if(File.Exists(meta)) File.Copy(meta,Path.Combine(target,"meta.lsx"));
        else File.WriteAllText(Path.Combine(target,"meta.lsx"),"<!-- Local discovery marker. Never installed. -->");
        void Snapshot(string file) {
            var relative=Path.GetRelativePath(original,file);
            var destination=Path.Combine(target,relative); Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            File.Copy(file,destination);
            paths[Path.Combine("Mods",mod,relative).Replace('\\','/')]=file;
            if(mod==module && Path.GetExtension(file).Equals(".txt",StringComparison.OrdinalIgnoreCase) && Path.GetFileName(Path.GetDirectoryName(file))=="Goals")
                hashes[Path.GetFileNameWithoutExtension(file)]=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(destination))).ToLowerInvariant();
        }
        foreach(var file in Directory.EnumerateFiles(source).Where(file=>Path.GetExtension(file) is ".div" or ".txt")) Snapshot(file);
        var goals=Path.Combine(source,"Goals");
        if(Directory.Exists(goals)) foreach(var file in Directory.EnumerateFiles(goals,"*.txt")) Snapshot(file);
        var ignores=Path.Combine(original,"Story","story_orphanqueries_ignore_local.txt"); if(File.Exists(ignores)) Snapshot(ignores);
    }
    dynamic fs=New("LSLib.LS.VFS");
    using IDisposable ownedFs=(IDisposable)fs;
    fs.AttachGameDirectory(request.GameDataPath,true,false); fs.AttachRoot(overlay); fs.FinishBuild();
    dynamic resources=New("LSLib.LS.ModResources");
    using IDisposable ownedResources=(IDisposable)resources;
    dynamic visitor=New("LSLib.LS.ModPathVisitor",(object)resources,(object)fs);
    var game=Enum.Parse(assembly.GetType("LSLib.LS.Story.Compiler.TargetGame",true)!,"BG3");
    visitor.GetType().GetField("Game").SetValue(visitor,game);
    visitor.CollectStoryGoals=true; visitor.Discover();
    dynamic compiler=New("LSLib.LS.Story.Compiler.Compiler");
    compiler.GetType().GetField("Game").SetValue(compiler,game);
    compiler.Context.Log.WarningSwitches["W27"]=false;
    dynamic loader=New("LSLib.LS.Story.Compiler.StoryHeaderLoader",(object)compiler.Context);
    Stream OpenInput(string file) {
        var normalized=file.Replace('\\','/');
        if(normalized.StartsWith("Mods/"+module+"/",StringComparison.OrdinalIgnoreCase))
            return File.OpenRead(Path.Combine(overlay,normalized.Replace('/',Path.DirectorySeparatorChar)));
        return fs.Open(file);
    }
    string? header=null,coercionWhitelist=null;
    foreach(var mod in mods.Reverse()) {
        if(!resources.Mods.ContainsKey(mod)) throw new InvalidOperationException("Dependency module not found in game files: "+mod);
        dynamic info=resources.Mods[mod];
        if(header==null && info.StoryHeaderFile!=null) header=(string)info.StoryHeaderFile;
        if(coercionWhitelist==null && info.TypeCoercionWhitelistFile!=null) coercionWhitelist=(string)info.TypeCoercionWhitelistFile;
    }
    const string missingInputs="OsiCheck needs an extracted story_header.div and raw dependency goals in the game Data/Mods folders. Retail .pak files alone are not supported. Use the extracted sources from your modding setup or select the Toolkit backend; the standalone backend does not load Toolkit DLLs.";
    if(header==null) throw new InvalidOperationException(missingInputs);
    if(mods.Length>1 && !mods.Where(mod=>mod!=module).Any(mod=>(int)resources.Mods[mod].Scripts.Count>0))
        throw new InvalidOperationException(missingInputs);
    var headerFile=Path.Combine(output,"story_header.div");
    using(Stream stream=OpenInput(header)) {
        using var reader=new StreamReader(stream);
        var contents=reader.ReadToEnd(); File.WriteAllText(headerFile,contents);
        using var headerStream=new MemoryStream(Encoding.UTF8.GetBytes(contents));
        dynamic declarations=loader.ParseHeader(headerStream);
        if(declarations==null) throw new InvalidOperationException("OsiCheck could not parse the selected story header: "+header);
        loader.LoadHeader(declarations);
    }
    if(coercionWhitelist!=null) {
        var allowed=new HashSet<string>();
        using Stream stream=OpenInput(coercionWhitelist); using var reader=new StreamReader(stream);
        while(reader.ReadLine() is string line) if(!string.IsNullOrWhiteSpace(line)) allowed.Add(line.Trim());
        compiler.TypeCoercionWhitelist=allowed;
    }
    // Match OsiCheck's ordering: its inference currently depends on goal traversal order.
    var goalsByName=new SortedDictionary<string,object>();
    var diagnostics=new List<object>();
    object Diagnostic(string? file,int? line,int? column,string severity,string code,string message)=>new {file,line,column,severity,code,message};
    string? Original(string? filename) {
        if(filename==null) return null;
        return paths.TryGetValue(filename.Replace('\\','/'),out var original)?original:null;
    }
    dynamic generator=New("LSLib.LS.Story.Compiler.IRGenerator",(object)compiler.Context);
    foreach(var mod in mods) {
        dynamic info=resources.Mods[mod];
        IEnumerable<string> scripts=mod==module
            ? Directory.EnumerateFiles(Path.Combine(overlay,"Mods",module,"Story","RawFiles","Goals"),"*.txt")
                .Select(file=>Path.GetRelativePath(overlay,file))
            : ((System.Collections.IEnumerable)info.Scripts).Cast<string>();
        foreach(string file in scripts) {
            using Stream stream=OpenInput(file);
            dynamic ast=generator.ParseGoal(file,stream);
            if(ast==null) {
                dynamic location=generator.LastLocation;
                diagnostics.Add(Diagnostic(Original(file),location==null?1:(int)location.StartLine,location==null?1:(int)location.StartColumn,"error","X00","Could not parse goal "+Path.GetFileName(file)));
                continue;
            }
            dynamic goal=generator.GenerateGoalIR(ast); goal.Name=Path.GetFileNameWithoutExtension(file);
            goalsByName[(string)goal.Name]=goal;
        }
        if(info.OrphanQueryIgnoreList!=null) {
            using Stream stream=OpenInput((string)info.OrphanQueryIgnoreList); using var reader=new StreamReader(stream);
            while(reader.ReadLine() is string line) {
                var match=Regex.Match(line,@"^([a-zA-Z0-9_]+)\s+([0-9]+)$");
                if(match.Success) compiler.IgnoreUnusedDatabases.Add(New("LSLib.LS.Story.Compiler.FunctionNameAndArity",match.Groups[1].Value,int.Parse(match.Groups[2].Value)));
            }
        }
    }
    var exempted=new List<string>();
    foreach(var item in request.KnownVanillaIssues) {
        var match=Regex.Match(item,@"^(DB_\w+)\((\d+)\)$");
        if(!match.Success) throw new ArgumentException("Invalid known vanilla database: "+item);
        // A project that mentions the name must satisfy the ordinary database checks.
        if(paths.Where(pair=>pair.Key.StartsWith("Mods/"+module+"/",StringComparison.OrdinalIgnoreCase) && pair.Key.EndsWith(".txt"))
                .Any(pair=>Regex.IsMatch(File.ReadAllText(Path.Combine(overlay,pair.Key.Replace('/',Path.DirectorySeparatorChar))),@"\b"+Regex.Escape(match.Groups[1].Value)+@"\s*\("))) continue;
        compiler.IgnoreUnusedDatabases.Add(New("LSLib.LS.Story.Compiler.FunctionNameAndArity",match.Groups[1].Value,int.Parse(match.Groups[2].Value)));
        exempted.Add(item);
    }
    foreach(dynamic goal in goalsByName.Values) compiler.AddGoal(goal);
    // Fail before emission on activation cycles rather than leaving the worker recursing.
    var active=new HashSet<string>(); var visited=new HashSet<string>();
    void Visit(string name) {
        if(visited.Contains(name) || !goalsByName.TryGetValue(name,out var value)) return;
        if(!active.Add(name)) throw new InvalidOperationException("Cycle in goal activation graph: "+name);
        dynamic goal=value; foreach(dynamic edge in goal.ParentTargetEdges) Visit((string)edge.Goal.Name);
        active.Remove(name); visited.Add(name);
    }
    foreach(var name in goalsByName.Keys) Visit(name);
    for(int iteration=0;compiler.PropagateRuleTypes();iteration++) if(iteration>=11) throw new InvalidOperationException("Type propagation did not converge.");
    compiler.VerifyIR();
    int errors=diagnostics.Count,warnings=0;
    foreach(dynamic item in compiler.Context.Log.Log) {
        bool error=item.Level.ToString()=="Error"; if(error) errors++; else warnings++;
        dynamic location=item.Location;
        diagnostics.Add(Diagnostic(location==null?null:Original((string)location.FileName),location==null?null:(int)location.StartLine,
            location==null?null:(int)location.StartColumn,error?"error":"warning",(string)item.Code,(string)item.Message));
    }
    object? binary=null;
    if(errors==0 && request.Action=="build") {
        dynamic emitter=New("LSLib.LS.Story.Compiler.StoryEmitter",(object)compiler.Context);
        dynamic story=emitter.EmitStory();
        var partial=Path.Combine(output,"story.div.osi.partial");
        using(Stream stream=File.Create(partial)) New("LSLib.LS.Story.StoryWriter").Write(stream,story,false);
        dynamic readback;
        using(Stream stream=File.OpenRead(partial)) readback=New("LSLib.LS.Story.StoryReader").Read(stream);
        int expectedRules=0,expectedGlobals=0,actualRules=0,actualGlobals=0;
        foreach(dynamic goal in goalsByName.Values) foreach(dynamic rule in goal.KBSection) { expectedRules++; if(rule.IsGlobal) expectedGlobals++; }
        foreach(dynamic pair in readback.Nodes) {
            dynamic rule=pair.Value;
            if(rule.GetType().Name!="RuleNode") continue;
            actualRules++;
            if(StoryGraph.IncomingGoal(rule,(uint)pair.Key)==0) actualGlobals++;
        }
        if(actualRules!=expectedRules || actualGlobals!=expectedGlobals || (int)readback.Enums.Count!=(int)story.Enums.Count)
            throw new InvalidOperationException($"Compiled story verification failed: rules {actualRules}/{expectedRules}, global rules {actualGlobals}/{expectedGlobals}.");
        foreach(dynamic pair in story.Enums) {
            uint id=(uint)pair.Key;
            if(!readback.Enums.ContainsKey(id)) throw new InvalidOperationException("Compiled enum table is missing: "+id);
            dynamic expected=pair.Value,actual=readback.Enums[id];
            if((ushort)actual.UnderlyingType!=(ushort)expected.UnderlyingType || (int)actual.Elements.Count!=(int)expected.Elements.Count)
                throw new InvalidOperationException("Compiled enum table differs: "+id);
            for(int index=0;index<(int)expected.Elements.Count;index++)
                if((string)actual.Elements[index].Name!=(string)expected.Elements[index].Name || (ulong)actual.Elements[index].Value!=(ulong)expected.Elements[index].Value)
                    throw new InvalidOperationException("Compiled enum member differs: "+id);
        }
        File.Move(partial,Path.Combine(output,"story.div.osi"));
        binary=new {rules=actualRules,global_rules=actualGlobals,enums=(int)readback.Enums.Count,enum_values_verified=true,readback_verified=true};
    }
    standardOutput.WriteLine(JsonSerializer.Serialize(new {success=errors==0,errors,warnings,diagnostics,
        source_sha256=hashes,mods,known_vanilla_exemptions=exempted,binary,header,header_file=headerFile,compiler="osicheck",
        dependency_input_mode=request.PackageOnly?"packages-only":"game-files",compiler_output=compilerOutput.ToString()}));
    return errors==0?0:1;
} catch(Exception error) {
    standardOutput.WriteLine(JsonSerializer.Serialize(new {success=false,error=error.Message,diagnostics=Array.Empty<object>(),compiler_output=compilerOutput.ToString()}));
    return 1;
}

sealed class Request {
    public string LibraryDir {get;set;}="";
    public string GameDataPath {get;set;}="";
    public string ProjectPath {get;set;}="";
    public string OutputDir {get;set;}="";
    public string Action {get;set;}="check";
    public string[] BaseMods {get;set;}=[];
    public string[] KnownVanillaIssues {get;set;}=[];
    public bool PackageOnly {get;set;}
}
