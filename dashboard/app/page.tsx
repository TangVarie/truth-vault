import { getDashboardData } from "@/lib/dashboard-data";
import Editorial from "@/components/Editorial";

/**
 * `/` = 「Bone & Ink」编辑级品牌叙事站(方向 A)。
 * 服务端拉同一份真数据(与 /console 复用 getDashboardData),交给客户端 <Editorial> 做编辑级滚动叙事。
 * /console 仍是暗色座舱 —— 同数据、反语法。force-dynamic 永远显实时真值。
 */
export const dynamic = "force-dynamic";

export default async function Page() {
  const data = await getDashboardData();
  return <Editorial data={data} />;
}
