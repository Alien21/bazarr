import { describe, expect, it, vi } from "vitest";
import plugin from "./bazarr-custom";
describe.each([
  {
    platform: "Windows",
    filename: String.raw`C:\work\bazarr\frontend\src\components\Search\Search.tsx`,
  },
  {
    platform: "Windows with forward slashes",
    filename: "C:/work/bazarr/frontend/src/components/Search/Search.tsx",
  },
  {
    platform: "POSIX",
    filename: "/work/bazarr/frontend/src/components/Search/Search.tsx",
  },
  {
    platform: "UNC",
    filename: String.raw`\\server\share\bazarr\frontend\src\components\Search\Search.tsx`,
  },
])("SCSS module imports on $platform paths", ({ filename }) => {
  it.each([
    "./Search.module.scss",
    "./Search.module.css",
    "./nested/../Search.module.scss",
    "../Search/Search.module.scss",
    "@/components/Search/Search.module.scss",
    "@/assets/shared.module.scss",
    "../../assets/shared.module.css",
    "../Other/styles.scss",
    "external-package/styles.module.scss",
  ])("allows %s", (value) => {
    const report = vi.fn();
    const listener = plugin.rules["no-cross-module-scss-import"].create({
      filename,
      report,
    });
    listener.ImportDeclaration({
      type: "ImportDeclaration",
      source: { type: "Literal", value },
    });
    expect(report).not.toHaveBeenCalled();
  });
  it.each([
    "../Other/Other.module.scss",
    "./nested/Other.module.css",
    "@/components/Other/Other.module.scss",
    "../../assets-other/shared.module.scss",
    "@/assets-other/shared.module.css",
  ])("rejects %s", (value) => {
    const report = vi.fn();
    const listener = plugin.rules["no-cross-module-scss-import"].create({
      filename,
      report,
    });
    const node = {
      type: "ImportDeclaration",
      source: { type: "Literal", value },
    };
    listener.ImportDeclaration(node);
    expect(report).toHaveBeenCalledExactlyOnceWith({
      node,
      message: expect.stringContaining("across directories"),
    });
  });
});
