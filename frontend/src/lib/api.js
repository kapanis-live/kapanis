import axios from "axios";

// The built panel is served by the API itself, so it calls its own origin (works on localhost and on the
// phone over Tailscale). Only the dev server (port 3000) needs the separate backend URL from .env.
const BACKEND_URL = window.location.port === "3000" ? process.env.REACT_APP_BACKEND_URL : "";
export const API = `${BACKEND_URL}/api`;

const api = axios.create({
  baseURL: API,
  withCredentials: true,
});

export function formatApiErrorDetail(detail) {
  if (detail == null) return "Bir şeyler ters gitti. Lütfen tekrar deneyin.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e))).filter(Boolean).join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}

export default api;
