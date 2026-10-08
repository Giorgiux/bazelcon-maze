"""Generates BuildInfo.java with build metadata for the engine.

When `volatile` is True the current build time (read from the workspace status
file) is baked in; set it False to emit a fixed placeholder instead.
"""

def _build_info_impl(ctx):
    out = ctx.actions.declare_file("BuildInfo.java")
    if ctx.attr.volatile:
        # Read the build time from the workspace status file and bake it in.
        ctx.actions.run_shell(
            inputs = [ctx.info_file],
            outputs = [out],
            command = """ts=$(grep '^STABLE_BUILD_TIME ' %s | cut -d' ' -f2-); printf 'package engine; public final class BuildInfo { public static final String BUILD_TIME = "%%s"; }\\n' "$ts" > %s""" % (ctx.info_file.path, out.path),
            mnemonic = "StampBuildInfo",
        )
    else:
        # Emit a fixed placeholder.
        ctx.actions.write(
            output = out,
            content = 'package engine; public final class BuildInfo { public static final String BUILD_TIME = "unset"; }\n',
        )
    return [DefaultInfo(files = depset([out]))]

build_info = rule(
    implementation = _build_info_impl,
    attrs = {
        "volatile": attr.bool(
            default = True,
            doc = "Bake the current build time in (True) or a fixed placeholder (False).",
        ),
    },
)
