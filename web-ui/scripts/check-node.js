const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

function parseMajor(version) {
  const match = /^v?(\d+)\./.exec(version);
  return match ? Number(match[1]) : null;
}

function nextDevArgs(extraArgs) {
  const nextBin = path.resolve(__dirname, "..", "node_modules", "next", "dist", "bin", "next");
  return ["--no-deprecation", nextBin, "dev", ...extraArgs];
}

function runDev(nodePath, extraArgs) {
  const child = spawn(nodePath, nextDevArgs(extraArgs), {
    stdio: "inherit",
    env: process.env,
  });
  child.on("exit", (code) => {
    process.exit(typeof code === "number" ? code : 1);
  });
  child.on("error", (err) => {
    console.error(`Failed to start dev server with ${nodePath}: ${err.message}`);
    process.exit(1);
  });
}

function main() {
  const major = parseMajor(process.version);
  if (major === null) {
    console.error(`Unsupported Node version string: ${process.version}`);
    process.exit(1);
  }

  const extraArgs = process.argv.slice(2);
  if (major < 20 || major >= 23) {
    const fallbackNode = "/opt/homebrew/opt/node@22/bin/node";
    if (fs.existsSync(fallbackNode)) {
      runDev(fallbackNode, extraArgs);
      return;
    }
    console.error(
      [
        `Unsupported Node.js version ${process.version}.`,
        "Use Node 20, 21, or 22 for this project.",
        "Tip: nvm use 22",
      ].join(" "),
    );
    process.exit(1);
  }

  runDev(process.execPath, extraArgs);
}

main();
