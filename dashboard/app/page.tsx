import { getDashboardData } from "@/lib/dashboard-data";
import Narrative from "@/components/Narrative";

/**
 * `/` = 滚动数据叙事站(官网×看板的"上半身")。
 * 服务端拉同一份真数据(与 /console 复用 getDashboardData),交给客户端 <Narrative> 做滚动叙事。
 * force-dynamic:永远显实时真值(与 /console 一致)。
 */
export const dynamic = "force-dynamic";

export default async function Page() {
  const data = await getDashboardData();
  return <Narrative data={data} />;
}
