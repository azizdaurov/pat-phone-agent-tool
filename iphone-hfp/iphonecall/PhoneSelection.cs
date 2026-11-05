// Selection is independent of Bluetooth names, country or Windows' display language.
static class PhoneSelection
{
    public static T? Choose<T>(IReadOnlyList<T> devices, Func<T, string> name, Func<T, string> id,
                               string? nameHint = null, string? deviceId = null) where T : class
    {
        var matches = devices.Where(d => !string.IsNullOrEmpty(deviceId)
            ? string.Equals(id(d), deviceId, StringComparison.OrdinalIgnoreCase)
            : string.IsNullOrEmpty(nameHint) || name(d).Contains(nameHint, StringComparison.OrdinalIgnoreCase)).ToList();
        if (matches.Count > 1)
            throw new InvalidOperationException("Several phones are paired and none has a phone line yet. Connect your phone to this " +
                                                "laptop in the phone's Bluetooth settings, or choose one in Pat's settings.");
        return matches.Count == 1 ? matches[0] : null;
    }

    // What Windows says about one paired phone. First is the phone chosen in Pat's settings, or Windows' default phone line
    // when none is chosen.
    public sealed record Candidate(string Id, string Name, bool Connected, bool HasLine, bool First, bool Default);

    // The order to try phones in: a phone that is connected beats one that isn't, whatever Windows' default says; among
    // those, the first choice, then one that already has a phone line, then Windows' default. A phone with no phone line is
    // only tried if it is the first choice, since Windows may make its line when it connects.
    public static List<Candidate> Order(IEnumerable<Candidate> phones) =>
        phones.Where(p => p.HasLine || p.First)
              .OrderByDescending(p => p.Connected)
              .ThenByDescending(p => p.First)
              .ThenByDescending(p => p.HasLine)
              .ThenByDescending(p => p.Default)
              .ToList();

    // `iphonecall self-test`: the order above, on made-up phones. Prints each case and returns how many failed.
    public static int SelfTest()
    {
        Candidate P(string id, bool connected, bool line, bool first = false, bool isDefault = false) =>
            new(id, id, connected, line, first, isDefault);
        var cases = new (string name, Candidate[] phones, string[] expected)[]
        {
            ("Windows' default is away, another phone is here with a line",
             new[] { P("old", false, true, first: true, isDefault: true), P("here", true, true) }, new[] { "here", "old" }),
            ("chosen phone is here: it goes first even before it has a line",
             new[] { P("chosen", true, false, first: true), P("other", true, true, isDefault: true) }, new[] { "chosen", "other" }),
            ("chosen phone is away, another is here",
             new[] { P("chosen", false, true, first: true), P("here", true, true) }, new[] { "here", "chosen" }),
            ("nothing is here: the first choice, then Windows' default",
             new[] { P("other", false, true, isDefault: true), P("chosen", false, true, first: true) }, new[] { "chosen", "other" }),
            ("a paired phone never set up for calls is not tried",
             new[] { P("here", true, true, first: true), P("drawer", true, false) }, new[] { "here" }),
            ("two phones here, none chosen: the one with a line, then Windows' default",
             new[] { P("noline", true, false), P("default", true, true, first: true, isDefault: true), P("line", true, true) },
             new[] { "default", "line" }),
        };
        int failed = 0;
        foreach (var (name, phones, expected) in cases)
        {
            var got = Order(phones).Select(p => p.Id).ToArray();
            bool ok = got.SequenceEqual(expected);
            if (!ok) failed++;
            Console.WriteLine($"{(ok ? "ok  " : "FAIL")} {name}: {string.Join(", ", got)}{(ok ? "" : $" (expected {string.Join(", ", expected)})")}");
        }
        Console.WriteLine(failed == 0 ? "all passed" : $"{failed} failed");
        return failed;
    }
}
