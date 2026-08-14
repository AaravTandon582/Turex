import { UpcomingScreen } from "@/components/layout/upcoming-screen";

export const metadata = { title: "Library" };

export default function LibraryPage() {
  return (
    <UpcomingScreen
      title="Library"
      description="Every paper you have collected, with what you have read and what you have not."
      milestone="Milestone 2"
      capabilities={[
        "Upload PDFs, or add papers by arXiv ID or DOI",
        "Watch Atlas parse each paper into sections, references, and metadata",
        "Organise by collection, tag, and reading status",
        "Filter and sort a library that stays fast at a thousand papers",
      ]}
    />
  );
}
