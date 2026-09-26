import { useState } from "react";
import { PublicHero } from "@/pages/public/Ozellikler";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { Mail, Send, MessageCircle } from "lucide-react";

export default function Iletisim() {
  const [form, setForm] = useState({ name: "", email: "", message: "" });
  const [sent, setSent] = useState(false);

  const submit = (e) => {
    e.preventDefault();
    setSent(true);
    toast.success("Mesajın alındı. En kısa sürede dönüş yapacağız.");
    setForm({ name: "", email: "", message: "" });
    setTimeout(() => setSent(false), 2500);
  };

  return (
    <div>
      <PublicHero
        eyebrow="İletişim"
        title="Bize ulaş"
        subtitle="Soru, geri bildirim veya iş birliği için yaz. Yatırım danışmanlığı vermediğimizi hatırlatırız."
      />
      <section className="mx-auto grid max-w-5xl gap-10 px-5 py-16 md:grid-cols-2">
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-xl border border-hairline bg-surface p-5">
            <Mail className="mt-0.5 h-5 w-5 text-t-2" />
            <div>
              <div className="text-sm font-semibold text-t-1">E-posta</div>
              <div className="text-sm text-t-2">merhaba@kapanis.io</div>
            </div>
          </div>
          <div className="flex items-start gap-3 rounded-xl border border-hairline bg-surface p-5">
            <MessageCircle className="mt-0.5 h-5 w-5 text-t-2" />
            <div>
              <div className="text-sm font-semibold text-t-1">Telegram</div>
              <div className="text-sm text-t-2">@kapanis_bot</div>
            </div>
          </div>
          <p className="text-xs leading-relaxed text-t-3">
            Not: Kapanış bir analiz ve karar çerçevesi aracıdır. Kişiye özel yatırım tavsiyesi, portföy yönetimi veya
            garanti getiri sunmuyoruz.
          </p>
        </div>

        <form onSubmit={submit} className="space-y-4" data-testid="contact-form">
          <div className="space-y-1.5">
            <Label htmlFor="c-name" className="text-t-2">Ad</Label>
            <Input id="c-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="bg-surface border-hairline text-t-1" data-testid="contact-name" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="c-email" className="text-t-2">E-posta</Label>
            <Input id="c-email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="bg-surface border-hairline text-t-1" data-testid="contact-email" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="c-msg" className="text-t-2">Mesaj</Label>
            <Textarea id="c-msg" required rows={5} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} className="bg-surface border-hairline text-t-1 resize-none" data-testid="contact-message" />
          </div>
          <Button type="submit" disabled={sent} className="w-full" data-testid="contact-submit">
            <Send className="h-4 w-4" /> {sent ? "Gönderildi" : "Gönder"}
          </Button>
        </form>
      </section>
    </div>
  );
}
