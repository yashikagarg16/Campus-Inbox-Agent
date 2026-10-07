// Records a narrated walkthrough of the app as a video (demo/out/*.webm).
//
//   npm run record                 # starts a fresh backend + frontend, records, stops them
//   npm run record -- --no-start   # use servers already running on :8000 and :5173
//   DEMO_SNAPSHOTS=1 npm run record # also save a screenshot at every caption, for review
//
// Needs GEMINI_API_KEY in backend/.env: the demo shows real extraction, not canned output.
// Uses a made-up profile and a synthetic email, so no personal data appears on screen.

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, renameSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "demo", "out");
const API = "http://localhost:8000";
const WEB = "http://localhost:5173";
const START = !process.argv.includes("--no-start");

const PROFILE = {
  name: "Demo Student",
  batch: 2027,
  cgpa: 8.2,
  cgpa_scale: 10,
  branch: "CSE",
  branch_aliases: [],
  tenth_percent: 91,
  twelfth_percent: 87,
  active_backlogs: 0,
  skills: ["Python", "SQL", "React"],
  resume_summary:
    "Built a stock-trading backtester in Python with FastAPI. Built a React dashboard for a college fest. Interested in data and backend engineering.",
};

const EMAILS = [
  `Dear Students,

Quantly is offering a Quant Research Internship for the 2027 and 2028 batches.
Please register only if you're 8.5+ out of 10.
Fill the form by 12 October 2026, 11:59 PM: https://forms.gle/demoQuantly

Thanks,
Placement Office`,
  `Dear all,

This week's openings (open to batch 2027 only):

1. Lumen Robotics - Embedded Software Intern
Branches: ECE, EEE
Apply by 14 Oct 2026, 5 PM: https://forms.gle/demoLumen

2. Cedar Bank - Data Analyst Intern
Minimum CGPA 7.5. All branches.
Apply by 16 Oct 2026, 5 PM: https://forms.gle/demoCedar

3. Brightpath Labs - Product Analyst
Students with a strong academic record are encouraged to apply.
Apply by 20 Oct 2026, 6 PM: https://forms.gle/demoBright

T&P Cell`,
];

const children = [];
let step = 0;

function start(name, cmd, args, cwd, env = {}) {
  const child = spawn(cmd, args, { cwd, env: { ...process.env, ...env }, shell: process.platform === "win32" });
  child.stderr.on("data", (d) => process.env.DEMO_DEBUG && process.stderr.write(`[${name}] ${d}`));
  children.push(child);
}

async function waitFor(url, timeoutMs = 60_000) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function stopAll() {
  for (const c of children) {
    if (process.platform === "win32") spawn("taskkill", ["/pid", String(c.pid), "/T", "/F"]);
    else c.kill();
  }
}

async function nav(page, name) {
  await page.getByRole("navigation").getByRole("link", { name, exact: true }).click();
}

async function caption(page, text) {
  await page.evaluate((t) => {
    let el = document.getElementById("demo-caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "demo-caption";
      el.style.cssText =
        "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);max-width:80%;z-index:99999;" +
        "background:rgba(15,23,42,.92);color:#fff;padding:12px 20px;border-radius:10px;" +
        "font:500 18px/1.4 system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.3);text-align:center";
      document.body.appendChild(el);
    }
    el.textContent = t;
  }, text);
  if (process.env.DEMO_SNAPSHOTS) await page.screenshot({ path: join(OUT, `step-${String(++step).padStart(2, "0")}.png`) });
  await page.waitForTimeout(Math.max(2500, text.length * 55));
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  if (START) {
    const db = join(OUT, "demo.db");
    rmSync(db, { force: true });
    const python = join(ROOT, "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    if (!existsSync(python)) throw new Error("Set up backend/.venv first (see README).");
    start("api", `"${python}"`, ["-m", "uvicorn", "app.main:create_app", "--factory", "--port", "8000"], join(ROOT, "backend"), {
      DATABASE_URL: `sqlite:///${db.replaceAll("\\", "/")}`,
      APP_TOKEN: "",
    });
    start("web", "npm", ["run", "dev", "--", "--port", "5173", "--strictPort"], join(ROOT, "frontend"));
  }
  await waitFor(`${API}/health`);
  await waitFor(WEB);
  const config = await (await fetch(`${API}/config`)).json();
  if (!config.llm_configured) throw new Error("The backend has no GEMINI_API_KEY. Add it to backend/.env.");

  const browser = await chromium.launch({ channel: process.env.DEMO_BROWSER ?? "msedge", slowMo: 40 });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: OUT, size: { width: 1440, height: 900 } },
  });
  const page = await context.newPage();
  const video = page.video();

  try {
    await page.goto(WEB);
    await caption(page, "Campus Inbox Agent: reads placement emails and checks eligibility. The LLM reads; plain code decides.");

    await nav(page, "Profile");
    await caption(page, "First, the student's profile. Eligibility is checked against these numbers in code.");
    const fill = async (label, value) => {
      const field = page.getByLabel(label, { exact: false }).first();
      await field.fill(String(value));
    };
    await fill("Name", PROFILE.name);
    await fill("Batch", PROFILE.batch);
    await fill("CGPA", PROFILE.cgpa);
    await fill("Branch", PROFILE.branch);
    await fill("10th %", PROFILE.tenth_percent);
    await fill("12th %", PROFILE.twelfth_percent);
    await fill("Active backlogs", PROFILE.active_backlogs);
    await fill("Skills", PROFILE.skills.join(", "));
    await fill("About you", PROFILE.resume_summary);
    await page.getByRole("button", { name: "Save profile" }).click();
    await page.getByText("Saved.").waitFor();

    await nav(page, "Add email");
    await caption(page, "Paste a real-style placement email: \"register only if you're 8.5+ out of 10\".");
    await page.getByLabel("Email text").fill(EMAILS[0]);
    await page.getByRole("button", { name: "Check eligibility" }).click();
    await caption(page, "Gemini extracts each field with the exact sentence that supports it. Code then verifies every quote.");
    await page.getByRole("heading", { name: "Rules checked" }).waitFor({ timeout: 90_000 });
    await caption(page, "8.2 is below 8.5, so: not eligible. That comparison is an if statement, not the LLM's opinion.");
    await page.getByRole("button", { name: /CGPA/ }).click();
    await caption(page, "Click a rule and the email scrolls to the sentence that proves it.");

    await nav(page, "Add email");
    await caption(page, "Now a weekly digest listing three companies in one email.");
    await page.getByLabel("Email text").fill(EMAILS[1]);
    await page.getByRole("button", { name: "Check eligibility" }).click();
    await page.getByText(/This email contains \d+ opportunities/).waitFor({ timeout: 90_000 });
    await caption(page, "Each company becomes its own opportunity, with its own verdict.");

    await nav(page, "Opportunities");
    await page.getByRole("list").first().waitFor();
    await caption(page, "The dashboard sorts everything by deadline. Vague criteria like 'strong academic record' are marked Needs review, never guessed.");

    await page.getByRole("link", { name: /Brightpath/ }).click().catch(() => {});
    await page.getByRole("heading", { name: "Rules checked" }).waitFor();
    await caption(page, "When the email can't be checked by code, the app says so and shows the sentence to read yourself.");

    await page.getByLabel(/Form questions/).fill("Why do you want to join Brightpath Labs?\nDescribe a project you are proud of.");
    await caption(page, "It can draft answers to form questions, using only facts from the profile.");
    await page.getByRole("button", { name: "Draft answers" }).click();
    await page.getByRole("button", { name: "Copy" }).first().waitFor({ timeout: 90_000 });
    await page.getByRole("heading", { name: "Draft answers" }).scrollIntoViewIfNeeded();
    await caption(page, "You edit and approve every draft. Missing facts are marked [NEEDS INPUT]. Nothing is ever submitted for you.");
    await caption(page, "Read-only. Evidence for every decision. 'Needs review' instead of guessing.");
  } catch (e) {
    await page.screenshot({ path: join(OUT, "failure.png") }).catch(() => {});
    throw e;
  } finally {
    await context.close();
    await browser.close();
    if (START) stopAll();
  }

  const recorded = await video.path();
  const stamp = new Date().toISOString().slice(0, 19).replaceAll(":", "-");
  const target = join(OUT, `campus-inbox-agent-demo-${stamp}.webm`);
  renameSync(recorded, target);
  for (const f of readdirSync(OUT)) if (f.endsWith(".webm") && join(OUT, f) !== target && !f.startsWith("campus-")) rmSync(join(OUT, f));
  console.log(`Demo video: ${target}`);
}

main().catch((e) => {
  console.error(e.message ?? e);
  if (START) stopAll();
  process.exit(1);
});
