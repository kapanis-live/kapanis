// Panelden bota işlem: kuyruğa yazılır, bot 15 sn içinde Telegram'daki fonksiyonların aynısıyla uygular.
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/api";

export async function sendAction(type, payload = {}, okText = "Bota iletildi.") {
  try {
    await api.post("/actions", { type, payload });
    toast.success(okText, { description: "Bot birkaç saniye içinde uygular; sonuç Telegram'a da gelir." });
    return true;
  } catch (err) {
    toast.error(formatApiErrorDetail(err.response?.data?.detail) || "İletilemedi.");
    return false;
  }
}
