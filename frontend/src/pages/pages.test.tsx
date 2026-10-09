import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "../App";
import type { OpportunityDetail, OpportunitySummary, Profile } from "../api";
import { filterOpportunities } from "./DashboardPage";
import { fromForm, toForm } from "./ProfilePage";

const EMAIL = "Batch 2027 only.\nMinimum CGPA 8.0 required.\nLast date: 20 Oct.";

const summary = (over: Partial<OpportunitySummary>): OpportunitySummary => ({
  id: 1,
  email_id: 1,
  subject: "Acme",
  company: "Acme",
  role: "Intern",
  deadline: "2099-10-20T17:00:00",
  deadline_passed: false,
  form_link: "https://forms.gle/x",
  verdict: "eligible",
  is_opportunity: true,
  created_at: "2026-10-07T09:00:00",
  ...over,
});

const detail: OpportunityDetail = {
  ...summary({}),
  email_text: EMAIL,
  received_at: "2026-10-07T09:00:00",
  sender: "tpo@college.edu",
  siblings: [],
  extraction: {},
  issues: [{ field: "min_12th_percent", reason: "evidence quote not found in the email", value: 90, evidence: "x" }],
  decision: {
    verdict: "needs_review",
    reasons: ["Your profile has no 12th percentage."],
    notes: [],
    deadline: null,
    deadline_passed: false,
    rules: [
      { rule: "batches", status: "pass", required: [2027], actual: 2027, evidence: "Batch 2027 only.", span: [0, 15], reason: "Your batch 2027 is in the allowed batches (2027)." },
      { rule: "min_cgpa", status: "fail", required: 8, actual: 7.5, evidence: "Minimum CGPA 8.0 required.", span: [17, 42], reason: "Your CGPA 7.5 is below the minimum 8." },
    ],
  },
  drafts: [],
};

function mockFetch(routes: Record<string, unknown>) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url).pathname;
    const key = `${init?.method ?? "GET"} ${path}`;
    if (!(key in routes)) return new Response(JSON.stringify({ detail: `no mock for ${key}` }), { status: 404 });
    return new Response(JSON.stringify(routes[key]), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const CONFIG = { llm_configured: true, imap_configured: false, auth_required: false };

afterEach(() => vi.unstubAllGlobals());

describe("dashboard", () => {
  it("filters by verdict and hides past deadlines", () => {
    const items = [
      summary({ id: 1, verdict: "eligible" }),
      summary({ id: 2, verdict: "not_eligible" }),
      summary({ id: 3, verdict: "eligible", deadline_passed: true }),
    ];
    expect(filterOpportunities(items, "all", false).map((o) => o.id)).toEqual([1, 2]);
    expect(filterOpportunities(items, "eligible", true).map((o) => o.id)).toEqual([1, 3]);
  });

  it("lists opportunities from the API", async () => {
    mockFetch({
      "GET /config": CONFIG,
      "GET /opportunities": [summary({ company: "Acme Analytics" }), summary({ id: 2, company: "Quantly", verdict: "needs_review" })],
    });
    render(
      <MemoryRouter initialEntries={["/app"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Acme Analytics")).toBeInTheDocument();
    expect(screen.getByText("Quantly")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Needs review/ }));
    expect(screen.queryByText("Acme Analytics")).not.toBeInTheDocument();
  });

  it("shows a clear error when the server is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    render(
      <MemoryRouter initialEntries={["/app"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/Can't reach the server/);
  });
});

describe("opportunity page", () => {
  it("shows rules, highlights evidence and lists unverified fields", async () => {
    mockFetch({ "GET /config": CONFIG, "GET /opportunities/1": detail });
    render(
      <MemoryRouter initialEntries={["/app/opportunities/1"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Your CGPA 7.5 is below the minimum 8.")).toBeInTheDocument();
    const marks = document.querySelectorAll("mark");
    expect([...marks].map((m) => m.textContent)).toEqual(["Batch 2027 only", "Minimum CGPA 8.0 required"]);
    expect(screen.getByText("Couldn't verify")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open form/ })).toHaveAttribute("href", "https://forms.gle/x");

    const cgpaRule = screen.getByRole("button", { name: /CGPA/ });
    await userEvent.click(cgpaRule);
    expect(cgpaRule).toHaveAttribute("aria-pressed", "true");
    expect(marks[1].className).toMatch(/ring-2/);
  });

  it("drafts answers and shows warnings", async () => {
    const fetchMock = mockFetch({
      "GET /config": CONFIG,
      "GET /opportunities/1": detail,
      "POST /opportunities/1/drafts": [
        { id: 5, opportunity_id: 1, question: "Why us?", answer: "Because [NEEDS INPUT: reason]", status: "draft", warnings: ["Fill in: [NEEDS INPUT: reason]"], updated_at: "2026-10-07T09:00:00" },
      ],
    });
    render(
      <MemoryRouter initialEntries={["/app/opportunities/1"]}>
        <App />
      </MemoryRouter>,
    );
    await userEvent.type(await screen.findByLabelText(/Form questions/), "Why us?");
    await userEvent.click(screen.getByRole("button", { name: "Draft answers" }));
    expect(await screen.findByText("Fill in: [NEEDS INPUT: reason]")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(JSON.parse(call[1]!.body as string)).toEqual({ questions: ["Why us?"] });
  });
});

describe("profile form", () => {
  it("round-trips values and turns blanks into null", () => {
    const p: Profile = {
      name: null, batch: 2027, cgpa: 8.4, cgpa_scale: 10, branch: "CSE", tenth_percent: null,
      twelfth_percent: 88, active_backlogs: 0, skills: ["Python", "SQL"], branch_aliases: ["CSE (AI&ML)"], resume_summary: null,
    };
    expect(fromForm(toForm(p))).toEqual(p);
    expect(fromForm({ ...toForm(p), cgpa: " ", skills: "Go, " })).toMatchObject({ cgpa: null, skills: ["Go"] });
  });

  it("saves and reports how many opportunities were re-checked", async () => {
    const profile: Profile = {
      name: null, batch: 2027, cgpa: 8.4, cgpa_scale: 10, branch: "CSE", tenth_percent: null,
      twelfth_percent: null, active_backlogs: null, skills: [], branch_aliases: [], resume_summary: null,
    };
    mockFetch({ "GET /config": CONFIG, "GET /profile": profile, "PUT /profile": { profile, reevaluated: 3 } });
    render(
      <MemoryRouter initialEntries={["/app/profile"]}>
        <App />
      </MemoryRouter>,
    );
    const form = (await screen.findByRole("button", { name: "Save profile" })).closest("form")!;
    expect(within(form).getByDisplayValue("CSE")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await waitFor(() => expect(screen.getByText(/Re-checked 3 opportunities/)).toBeInTheDocument());
  });
});

describe("sign-in and demo", () => {
  const DEMO = { demo_mode: true, owner_login: true, llm_configured: false, imap_configured: false, auth_required: true };

  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("shows the sign-in page and lets visitors open the demo", async () => {
    mockFetch({ "GET /config": DEMO, "GET /opportunities": [summary({ company: "Acme Analytics" })] });
    render(
      <MemoryRouter initialEntries={["/app"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Explore the live demo/ }));
    expect(await screen.findByText("Acme Analytics")).toBeInTheDocument();
    expect(screen.getByText("Demo visitor")).toBeInTheDocument();
  });

  it("signs the owner in and stores the token", async () => {
    const fetchMock = mockFetch({
      "GET /config": DEMO,
      "POST /auth/login": { token: "tok123", email: "owner@example.com", expires_in: 100 },
      "GET /opportunities": [],
    });
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    await userEvent.type(await screen.findByLabelText("Email"), "owner@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "secret-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("owner@example.com")).toBeInTheDocument();
    expect(localStorage.getItem("cia.token")).toBe("tok123");
    const login = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/auth/login"))!;
    expect(JSON.parse(login[1]!.body as string)).toEqual({ email: "owner@example.com", password: "secret-password" });
  });

  it("locks live checks for demo visitors", async () => {
    sessionStorage.setItem("cia.demo", "1");
    mockFetch({ "GET /config": DEMO });
    render(
      <MemoryRouter initialEntries={["/app/add"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/Live checks are for signed-in users/)).toBeInTheDocument();
  });
});
