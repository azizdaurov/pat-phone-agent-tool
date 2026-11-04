// No Windows phone APIs are used: these tests cannot connect, dial or route call audio.
int passed = 0;
void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
    passed++;
}
Phone? Choose(Phone[] devices, string? hint = null, string? id = null) =>
    PhoneSelection.Choose(devices, d => d.Name, d => d.Id, hint, id);
bool Ambiguous(Phone[] devices, string? hint = null)
{
    try { Choose(devices, hint); return false; }
    catch (InvalidOperationException) { return true; }
}

var renamed = new Phone("first", "Мой телефон");
var second = new Phone("second", "Maya's mobile");
Check(Choose(new[] { renamed }) == renamed, "A renamed phone must be found without an English name hint.");
Check(Choose(Array.Empty<Phone>()) == null, "No phones must return no match.");
Check(Ambiguous(new[] { renamed, second }), "Multiple phones must never silently choose the first.");
Check(Choose(new[] { renamed, second }, id: "second") == second, "An explicit device ID must select that phone.");
Check(Choose(new[] { renamed, second }, hint: "MAYA") == second, "Explicit names must match without case sensitivity.");
Check(Choose(new[] { renamed, second }, id: "missing") == null, "A missing ID must not fall back to another phone.");
Check(Ambiguous(new[] { new Phone("a", "Phone one"), new Phone("b", "Phone two") }, "Phone"), "An ambiguous name must be refused.");
Console.WriteLine($"{passed} phone selection tests passed.");

record Phone(string Id, string Name);
