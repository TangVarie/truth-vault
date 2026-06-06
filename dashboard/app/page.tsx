import { getDashData } from "@/lib/data";
import Narrative from "@/components/Narrative";

// 叙事站始终拉实时大数(force-dynamic)。docs/24。
export const dynamic = "force-dynamic";

export default async function Page() {
  const data = await getDashData();
  return <Narrative data={data} />;
}
