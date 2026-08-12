import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Utterance } from "@/features/translate/model/types";
import { TranscriptView } from "@/pages/translate/ui/TranscriptView";

const langName = (code: string | null) =>
  code === "es" ? "Spanish" : code === "en" ? "English" : (code ?? "");

function utt(overrides: Partial<Utterance> = {}): Utterance {
  return {
    speaker: "user-1",
    language: "es",
    spokenLang: null,
    source: "hola",
    translation: "hello",
    live: false,
    ts: Date.now(),
    ...overrides,
  };
}

describe("TranscriptView", () => {
  describe("columns view", () => {
    it("shows empty placeholders for both sides with no utterances", () => {
      render(<TranscriptView utterances={[]} view="columns" langName={langName} />);
      expect(screen.getByText("Source speech appears here.")).toBeInTheDocument();
      expect(screen.getByText("Translation appears here.")).toBeInTheDocument();
    });

    it("renders source text on the left and translation on the right, with the raw speaker id", () => {
      render(<TranscriptView utterances={[utt()]} view="columns" langName={langName} />);
      expect(screen.getByText("hola")).toBeInTheDocument();
      expect(screen.getByText("hello")).toBeInTheDocument();
      expect(screen.getAllByText("user-1")).toHaveLength(2); // shown on both sides
    });
  });

  describe("stacked view", () => {
    it("shows a card per utterance with speaker name, language, source and translation together", () => {
      render(
        <TranscriptView
          utterances={[utt({ speaker: "user-1" })]}
          view="stacked"
          langName={langName}
        />,
      );
      expect(screen.getByText("Speaker 1")).toBeInTheDocument(); // pretty label, not raw "user-1"
      expect(screen.getByText("hola")).toBeInTheDocument();
      expect(screen.getByText("hello")).toBeInTheDocument();
      expect(screen.getByText(/Spanish/)).toBeInTheDocument();
    });

    it("shows a spoken-language tag when spokenLang differs from the utterance's own language", () => {
      render(
        <TranscriptView
          utterances={[utt({ language: "es", spokenLang: "en" })]}
          view="stacked"
          langName={langName}
        />,
      );
      expect(screen.getByText(/spoken in English/)).toBeInTheDocument();
    });

    it("renders multiple utterances in order", () => {
      render(
        <TranscriptView
          utterances={[utt({ source: "one" }), utt({ source: "two" })]}
          view="stacked"
          langName={langName}
        />,
      );
      expect(screen.getByText("one")).toBeInTheDocument();
      expect(screen.getByText("two")).toBeInTheDocument();
    });
  });

  describe("focus view", () => {
    it("renders only the last utterance", () => {
      render(
        <TranscriptView
          utterances={[utt({ source: "one" }), utt({ source: "two" })]}
          view="focus"
          langName={langName}
        />,
      );
      expect(screen.queryByText("one")).not.toBeInTheDocument();
      expect(screen.getByText("two")).toBeInTheDocument();
    });

    it("shows a neutral empty state with no utterances", () => {
      render(<TranscriptView utterances={[]} view="focus" langName={langName} />);
      expect(screen.getByText("Nothing yet.")).toBeInTheDocument();
    });
  });
});
