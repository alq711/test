// QuickAdd 매크로용 스크립트: 지금 열린 책 노트를 한글(.hwpx)로 만든다.
//
// 설치 (한 번만):
//   1. PC에 hwpxwriter 설치:  py -m pip install git+https://github.com/alq711/test
//   2. 이 파일을 볼트 안 아무 곳(예: 20_Teaching_Materials/교재/스크립트/)에 넣는다.
//   3. QuickAdd 설정 → Manage Macros → 새 매크로 → User Script 로 이 파일을 고른다.
//   4. QuickAdd 선택지에 그 매크로를 추가하고 번개 아이콘을 켜면 명령 팔레트에
//      'QuickAdd: hwpx 만들기' 가 생긴다. 설정 → 단축키에서 키를 붙인다.
//
// 열린 노트가 책 노트(template 속성)면 hwpx를 만들고, 아니면 볼트 전체를 점검한다.
// 결과 파일 위치는 책 노트 속성 output (없으면 노트 옆).

const { execFile } = require("child_process");
const path = require("path");

// md2hwpx 를 찾는 순서. 안 되면 첫 줄을 python 이 있는 전체 경로로 바꾼다.
const COMMANDS = [
  ["md2hwpx", []],
  ["py", ["-m", "hwpxwriter"]],
  ["python", ["-m", "hwpxwriter"]],
];

function run(args, cwd) {
  return new Promise((resolve) => {
    const tryAt = (i) => {
      if (i >= COMMANDS.length) {
        resolve({ ok: false, out: "md2hwpx 를 찾지 못했습니다. hwpxwriter 설치를 확인해 주세요." });
        return;
      }
      const [cmd, pre] = COMMANDS[i];
      execFile(cmd, [...pre, ...args], { cwd, windowsHide: true, encoding: "utf8",
                                         env: { ...process.env, PYTHONUTF8: "1" } },
        (err, stdout, stderr) => {
          if (err && err.code === "ENOENT") return tryAt(i + 1);
          resolve({ ok: !err, out: `${stdout || ""}${stderr || ""}`.trim() });
        });
    };
    tryAt(0);
  });
}

module.exports = async (params) => {
  const { app, obsidian } = params;
  const vaultDir = app.vault.adapter.basePath;
  const file = app.workspace.getActiveFile();
  const meta = file ? app.metadataCache.getFileCache(file)?.frontmatter || {} : {};
  const isBook = file && file.extension === "md" && (meta.template || meta.type === "book");

  const args = isBook ? [path.join(vaultDir, file.path), "--vault", vaultDir] : ["--check", vaultDir];
  new obsidian.Notice(isBook ? `hwpx 만드는 중: ${file.basename}` : "볼트 점검 중…");
  const { ok, out } = await run(args, vaultDir);
  new obsidian.Notice(out || (ok ? "완료" : "실패"), ok ? 8000 : 0);
  console.log("[hwpxwriter]", out);
};
