// Panelden bota işlem: kuyruğa yazılır, bot 15 sn içinde Telegram'daki fonksiyonların aynısıyla uygular.
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "@/lib/api";
import { translate, currentLang } from "@/lib/i18n";

const tx = (s, v) => translate(currentLang(), s, v);

export async function sendAction(type, payload = {}, okText) {
  try {
    await api.post("/actions", { type, payload });
    toast.success(okText === undefined ? tx("Bota iletildi.") : okText, { description: tx("Bot birkaç saniye içinde uygular; sonuç Telegram'a da gelir.") });
    return true;
  } catch (err) {
    toast.error(formatApiErrorDetail(err.response?.data?.detail) || tx("İletilemedi."));
    return false;
  }
}
