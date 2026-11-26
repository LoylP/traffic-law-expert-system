"use client";

import { Clock } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ChatInput } from "@/components/chat/ChatInput";
import { LoadingSkeleton } from "@/components/chat/LoadingSkeleton";
import { MessageBubble } from "@/components/chat/MessageBubble";
import { WelcomeScreen } from "@/components/chat/WelcomeScreen";
import { ExplanationPanel } from "@/components/expert/ExplanationPanel";
import { AppHeader } from "@/components/layout/AppHeader";
import { Sidebar, type SidebarProps } from "@/components/layout/Sidebar";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Sheet } from "@/components/ui/Sheet";
import { consult, fetchHistory, legacySearch, type SearchOptions } from "@/lib/api";
import {
  mergeCases,
  rememberCase,
  SESSION_TTL_MS,
  turnsFromHistory,
  useStoredCases,
} from "@/lib/cases";
import { newId, truncate } from "@/lib/format";
import { useMediaQuery } from "@/lib/hooks";
import type { ChatMode, ChatTurn, HistoryItem } from "@/types/chat";

type Conversation = {
  sessionId: string;
  turns: ChatTurn[];
  /** Why the composer is closed (old case whose server session is gone). */
  closed: string | null;
};

const emptyConversation = (): Conversation => ({ sessionId: newId(), turns: [], closed: null });

const now = () => new Date().toISOString();

export function ChatWorkspace() {
  const [conversation, setConversation] = useState<Conversation>(emptyConversation);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [mode, setMode] = useState<ChatMode>("expert");
  const [searchOptions, setSearchOptions] = useState<SearchOptions>({ topK: 3, alpha: 0.5 });
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [explainedId, setExplainedId] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const storedCases = useStoredCases();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  // Replaced with the conversation, so a late response never lands in a new case.
  const requestRef = useRef<AbortController | null>(null);

  const { sessionId, turns, closed } = conversation;

  const refreshHistory = useCallback(() => {
    fetchHistory()
      .then(setHistory)
      .catch(() => {
        // the sidebar then lists only the cases stored in this browser
      });
  }, []);

  useEffect(refreshHistory, [refreshHistory]);

  // Show the latest question at the top, with its answer below.
  useEffect(() => {
    const questions = listRef.current?.querySelectorAll('[data-turn="user"]');
    questions?.[questions.length - 1]?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [turns.length, pending]);

  const reset = (next: Conversation) => {
    requestRef.current?.abort();
    requestRef.current = null;
    setConversation(next);
    setPending(false);
    setDraft("");
    setExplainedId(null);
    setMenuOpen(false);
  };

  const startCase = () => {
    reset(emptyConversation());
    inputRef.current?.focus();
  };

  const openCase = (id: string) => {
    if (id === sessionId) {
      setMenuOpen(false);
      return;
    }
    const restored = turnsFromHistory(id, history);
    const lastAt = restored.at(-1)?.at;
    const expired = !lastAt || Date.now() - new Date(lastAt).getTime() > SESSION_TTL_MS;
    let notice: string | null = null;
    if (!restored.length) {
      notice = "Không tìm thấy nội dung của vụ việc này trong lịch sử máy chủ.";
    } else if (expired) {
      notice = "Đang xem lại. Máy chủ chỉ giữ dữ kiện của vụ việc trong 30 phút.";
    }
    setMode("expert");
    reset({ sessionId: id, turns: restored, closed: notice });
  };

  const send = async (text: string, { retry = false } = {}) => {
    if (pending || closed) return;
    const controller = new AbortController();
    requestRef.current = controller;
    const current = { sessionId, mode };
    const append = (turn: ChatTurn) =>
      setConversation((state) => ({ ...state, turns: [...state.turns, turn] }));

    setConversation((state) => ({
      ...state,
      turns: retry
        ? state.turns.filter((turn) => turn.kind !== "error")
        : [
            ...state.turns.filter((turn) => turn.kind !== "error"),
            { id: newId(), at: now(), kind: "user", text },
          ],
    }));
    setDraft("");
    setPending(true);
    if (current.mode === "expert") rememberCase(current.sessionId, text);

    try {
      if (current.mode === "expert") {
        const result = await consult(text, current.sessionId, controller.signal);
        if (requestRef.current !== controller) return;
        const id = newId();
        append({ id, at: now(), kind: "consult", result });
        // An open panel follows the newest answer.
        setExplainedId((open) => (open ? id : null));
      } else {
        const response = await legacySearch(current.mode, text, searchOptions, controller.signal);
        if (requestRef.current !== controller) return;
        append({ id: newId(), at: now(), kind: "legacy", response });
      }
    } catch (error) {
      if (requestRef.current !== controller) return;
      const message = error instanceof Error ? error.message : "Đã xảy ra lỗi không xác định.";
      append({ id: newId(), at: now(), kind: "error", message, retryText: text });
    } finally {
      if (requestRef.current === controller) {
        setPending(false);
        refreshHistory();
      }
    }
  };

  const prefill = (text: string) => {
    setDraft(text);
    inputRef.current?.focus();
  };

  const explainedIndex = turns.findIndex((turn) => turn.id === explainedId);
  const explained = turns[explainedIndex];
  // What the explained answer is based on: its question, plus the earlier turns it
  // follows up on (the server only carries facts over after "need_info").
  const explainedMessages: string[] = [];
  for (let i = explainedIndex - 1; i >= 0; i -= 1) {
    const turn = turns[i];
    if (turn.kind === "user") explainedMessages.unshift(turn.text);
    else if (turn.kind !== "consult" || turn.result.status !== "need_info") break;
  }
  const panel =
    explained?.kind === "consult" ? (
      <ExplanationPanel
        key={explained.id}
        explanation={explained.result.explanation}
        messages={explainedMessages}
        onClose={() => setExplainedId(null)}
      />
    ) : null;

  // With the panel open, the header names the question of the explained answer.
  const firstQuestion = turns.find((turn) => turn.kind === "user");
  const heading =
    (panel ? explainedMessages.at(-1) : undefined) ??
    (firstQuestion?.kind === "user" ? firstQuestion.text : undefined);
  const title = heading ? truncate(heading) : "Vụ việc mới";

  const sidebarProps: SidebarProps = {
    cases: mergeCases(storedCases, history),
    activeId: sessionId,
    onNewCase: startCase,
    onOpenCase: openCase,
    mode,
    onModeChange: (next) => {
      setMode(next);
      // Expert answers and legacy results are not mixed in one case.
      reset(emptyConversation());
    },
    searchOptions,
    onSearchOptionsChange: setSearchOptions,
  };

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="hidden w-[260px] shrink-0 border-r border-line bg-surface lg:block">
        <Sidebar {...sidebarProps} />
      </aside>
      <Sheet
        open={menuOpen && !isDesktop}
        onClose={() => setMenuOpen(false)}
        side="left"
        label="Menu"
      >
        <Sidebar {...sidebarProps} />
      </Sheet>

      <main className="flex min-w-0 flex-1 flex-col">
        <AppHeader
          title={title}
          badge={mode === "expert" ? "NĐ 168/2024/NĐ-CP" : "Tra cứu cũ"}
          onOpenMenu={() => setMenuOpen(true)}
        />
        <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto px-4">
          <div className="mx-auto h-full max-w-[760px]">
            {turns.length === 0 && !closed ? (
              <WelcomeScreen onPick={(text) => void send(text)} />
            ) : (
              <div aria-live="polite" aria-relevant="additions" className="space-y-5 pt-5 pb-16">
                {turns.map((turn, index) => {
                  const latest = index === turns.length - 1 && !pending && !closed;
                  return (
                    <MessageBubble
                      key={turn.id}
                      turn={turn}
                      explaining={turn.id === explainedId}
                      onExplain={() =>
                        setExplainedId((open) => (open === turn.id ? null : turn.id))
                      }
                      onFollowUp={latest ? () => inputRef.current?.focus() : undefined}
                      onAnswer={latest ? (reply) => void send(reply) : undefined}
                      onSuggest={latest ? prefill : undefined}
                      onRetry={
                        latest && turn.kind === "error"
                          ? () => void send(turn.retryText, { retry: true })
                          : undefined
                      }
                    />
                  );
                })}
                {pending && <LoadingSkeleton legacy={mode !== "expert"} />}
              </div>
            )}
          </div>
        </div>

        <div className="shrink-0 px-4 pb-2">
          <div className="mx-auto max-w-[760px] space-y-2">
            {closed ? (
              <Callout icon={Clock}>
                <div className="flex flex-wrap items-center gap-3">
                  <span>{closed}</span>
                  <Button variant="primary" onClick={startCase}>
                    Vụ việc mới
                  </Button>
                </div>
              </Callout>
            ) : (
              <ChatInput
                value={draft}
                onChange={setDraft}
                onSend={(text) => void send(text)}
                busy={pending}
                placeholder={
                  mode === "expert"
                    ? "Mô tả tình huống: loại xe, hành vi, nồng độ cồn, tốc độ…"
                    : "Nhập hành vi cần tra cứu…"
                }
                showQuickStarts={mode === "expert" && turns.length === 0 && !pending}
                inputRef={inputRef}
              />
            )}
            <p className="text-center text-xs text-fg-subtle">
              Kết quả mang tính tham khảo, không thay thế quyết định xử phạt của cơ quan có thẩm
              quyền.
            </p>
          </div>
        </div>
      </main>

      {isDesktop ? (
        panel && (
          <aside
            aria-label="Giải thích"
            className="animate-enter w-[clamp(380px,29vw,420px)] shrink-0 border-l border-line bg-surface"
          >
            {panel}
          </aside>
        )
      ) : (
        <Sheet
          open={panel !== null}
          onClose={() => setExplainedId(null)}
          side="bottom"
          label="Vì sao?"
        >
          {panel}
        </Sheet>
      )}
    </div>
  );
}
