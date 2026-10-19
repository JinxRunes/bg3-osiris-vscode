// Global IFF rules are identified by their serialized incoming activation link.
// Per-goal decompilation can omit them and DerivedGoalRef is reconstructed by the reader.
internal static class StoryGraph {
    internal static uint? IncomingGoal(dynamic rule,uint index) {
        dynamic parent=rule.ParentRef.Resolve();
        var entries=parent.GetType().GetField("ReferencedBy");
        if(entries!=null) {
            foreach(dynamic link in (System.Collections.IEnumerable)entries.GetValue(parent)!)
                if((uint)link.NodeRef.Index==index) return (uint)link.GoalRef.Index;
        } else {
            var next=parent.GetType().GetField("NextNode");
            if(next!=null) {
                dynamic link=next.GetValue(parent)!;
                if((uint)link.NodeRef.Index==index) return (uint)link.GoalRef.Index;
            }
        }
        throw new InvalidOperationException("Compiled rule has no incoming activation link: "+index);
    }
}
