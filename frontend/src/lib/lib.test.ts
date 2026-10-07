import { deadlineUrgency, formatDeadline, parseServerDate, relativeDeadline, splitList } from "./format";
import { segmentText, worstStatus } from "./highlight";

describe("segmentText", () => {
  const text = "Batch 2027 only. Minimum CGPA 8.0.";

  it("returns the whole text when there are no marks", () => {
    expect(segmentText(text, [])).toEqual([{ text, start: 0, marks: [] }]);
  });

  it("splits around a mark and keeps every character", () => {
    const segs = segmentText(text, [{ key: 0, start: 17, end: 33, status: "pass" }]);
    expect(segs.map((s) => s.text).join("")).toBe(text);
    expect(segs[1]).toMatchObject({ text: "Minimum CGPA 8.0", marks: [{ key: 0 }] });
  });

  it("handles overlapping marks", () => {
    const segs = segmentText("abcdefgh", [
      { key: 0, start: 0, end: 5, status: "pass" },
      { key: 1, start: 3, end: 8, status: "fail" },
    ]);
    expect(segs.map((s) => [s.text, s.marks.map((m) => m.key)])).toEqual([
      ["abc", [0]],
      ["de", [0, 1]],
      ["fgh", [1]],
    ]);
    expect(worstStatus(segs[1].marks)).toBe("fail");
  });

  it("ignores out-of-range marks", () => {
    expect(segmentText("abc", [{ key: 0, start: 2, end: 99, status: "pass" }])).toHaveLength(1);
  });
});

describe("dates", () => {
  it("treats naive server datetimes as IST", () => {
    expect(parseServerDate("2026-10-20T17:00:00").toISOString()).toBe("2026-10-20T11:30:00.000Z");
    expect(parseServerDate("2026-10-20T11:30:00Z").toISOString()).toBe("2026-10-20T11:30:00.000Z");
  });

  it("formats in IST", () => {
    expect(formatDeadline("2026-10-20T17:00:00")).toMatch(/20 Oct/);
    expect(formatDeadline("2026-10-20T17:00:00")).toMatch(/5:00\s?pm/i);
    expect(formatDeadline(null)).toBe("No deadline found");
  });

  it("describes relative time and urgency", () => {
    const now = new Date("2026-10-07T06:30:00Z"); // 12:00 IST
    expect(relativeDeadline("2026-10-10T12:00:00", now)).toBe("in 3 days");
    expect(relativeDeadline("2026-10-07T17:00:00", now)).toBe("in 5 hours");
    expect(relativeDeadline("2026-10-05T12:00:00", now)).toBe("2 days ago");
    expect(deadlineUrgency("2026-10-08T12:00:00", now)).toBe("urgent");
    expect(deadlineUrgency("2026-10-12T12:00:00", now)).toBe("soon");
    expect(deadlineUrgency("2026-11-12T12:00:00", now)).toBe("later");
    expect(deadlineUrgency("2026-10-01T12:00:00", now)).toBe("passed");
    expect(deadlineUrgency(null, now)).toBe("none");
  });
});

it("splitList trims and drops empties", () => {
  expect(splitList(" Python, SQL ,, Go ")).toEqual(["Python", "SQL", "Go"]);
});
