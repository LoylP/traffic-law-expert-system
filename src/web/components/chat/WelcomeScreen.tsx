import { SuggestionGrid } from "@/components/expert/SuggestionGrid";

export function WelcomeScreen({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="@container flex min-h-full flex-col justify-center gap-6 py-6">
      <h2 className="mx-auto max-w-xl text-center text-xl leading-snug font-semibold text-balance sm:text-2xl">
        Mô tả tình huống, hệ thống sẽ xác định lỗi, mức phạt và giải thích căn cứ
      </h2>
      <SuggestionGrid onPick={onPick} />
    </div>
  );
}
