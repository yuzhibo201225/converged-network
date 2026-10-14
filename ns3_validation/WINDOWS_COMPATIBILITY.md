# Windows initialization compatibility change

The official ns-3.47 source was built with MSYS2 MinGW64 GCC 16.2. The unmodified
DLL failed at startup with Windows error 1114. A GDB backtrace showed a C++
exception in Time::StaticInit called by another translation unit's global
constructor while attempting to lock the namespace-scope g_markingMutex in
src/core/model/time.cc.

The local compatibility change replaces that mutex with a function-local static
returned by MarkingMutex(), and replaces all five lock expressions. This ensures
construction precedes any header-triggered Time initialization. It changes
initialization lifetime, not queue scheduling, rate calculation or timestamps.
This is a local change, not an official ns-3 fix or version claim.

To reproduce, expand the official archive and replace
`static std::mutex g_markingMutex;` with:

```cpp
static std::mutex& MarkingMutex()
{
    static std::mutex mutex;
    return mutex;
}
```

Replace every `std::unique_lock lock{g_markingMutex};` with
`std::unique_lock lock{MarkingMutex()};`, then rebuild core and relink the
validation executable. Set NS3_WARNINGS_AS_ERRORS=OFF for the compiler's newer
unused-variable warnings. Disclose this change with the software version.
A successful smoke run is required; the source change alone is not validation.
