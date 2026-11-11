import { splitQuestion } from "./text";

describe("splitQuestion (D92)", () => {
  it("takes a repeated question off the end of the message", () => {
    expect(splitQuestion("Try it now. What did you notice?", "What did you notice?")).toEqual([
      "Try it now.",
      "What did you notice?",
    ]);
  });
  it("does not repeat a question that sits inside the message", () => {
    expect(splitQuestion("What did you notice? Take your time.", "What did you notice?")).toEqual([
      "What did you notice? Take your time.",
      null,
    ]);
  });
  it("keeps a separate question", () => {
    expect(splitQuestion("Try it now.", "How was it?")).toEqual(["Try it now.", "How was it?"]);
    expect(splitQuestion("Try it now.", null)).toEqual(["Try it now.", null]);
  });
});
