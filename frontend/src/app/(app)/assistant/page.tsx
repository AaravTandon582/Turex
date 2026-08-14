import { UpcomingScreen } from "@/components/layout/upcoming-screen";

export const metadata = { title: "Assistant" };

export default function AssistantPage() {
  return (
    <UpcomingScreen
      title="Research assistant"
      description="An assistant that reasons over your library, not the open internet."
      milestone="Milestone 3"
      capabilities={[
        "Ask questions across your papers and get answers grounded in retrieved passages",
        "Follow every claim back to the exact page and paragraph it came from",
        "Switch modes — explain, critique, ideate, design an experiment, or study",
        "See clearly when Atlas is inferring rather than quoting, and when it does not know",
      ]}
    />
  );
}
