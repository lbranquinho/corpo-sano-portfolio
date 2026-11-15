import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, onSessionExpired, refreshSession, setAccessToken } from "./api";

export type Me = {
  id: string;
  name: string;
  email: string;
  role: string;
  role_name: string;
  professional_id: string | null;
  permissions: string[];
  must_change_password: boolean;
  session_idle_minutes: number;
  clinic_name: string | null;
  has_logo: boolean;
};

type AuthState = {
  me: Me | null;
  loading: boolean;
  notice: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: (reason?: string) => Promise<void>;
  reload: () => Promise<void>;
  can: (...perms: string[]) => boolean;
  canAny: (...perms: string[]) => boolean;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const qc = useQueryClient();
  const lastActivity = useRef(Date.now());

  const loadMe = useCallback(async () => {
    const data = await api<Me>("/auth/me");
    setMe(data);
  }, []);

  const logout = useCallback(
    async (reason?: string) => {
      try {
        await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin" });
      } catch {
        /* offline */
      }
      setAccessToken(null);
      setMe(null);
      qc.clear();
      if (reason) setNotice(reason);
    },
    [qc],
  );

  // restaura a sessão (cookie httpOnly) ao abrir o sistema
  useEffect(() => {
    (async () => {
      if (await refreshSession()) {
        try {
          await loadMe();
        } catch {
          setMe(null);
        }
      }
      setLoading(false);
    })();
  }, [loadMe]);

  useEffect(() => {
    onSessionExpired((reason) => {
      if (reason === "troca_senha") {
        loadMe().catch(() => undefined);
        return;
      }
      setMe(null);
      setNotice(reason);
      qc.clear();
    });
  }, [loadMe, qc]);

  // bloqueio automático por inatividade + renovação silenciosa enquanto há atividade
  useEffect(() => {
    if (!me) return;
    const mark = () => (lastActivity.current = Date.now());
    const events = ["mousemove", "keydown", "click", "touchstart", "scroll"];
    events.forEach((e) => window.addEventListener(e, mark, { passive: true }));
    const idleMs = (me.session_idle_minutes || 30) * 60_000;
    const timer = window.setInterval(() => {
      const idle = Date.now() - lastActivity.current;
      if (idle >= idleMs) {
        logout("Sessão encerrada por inatividade. Entre novamente.");
      }
    }, 15_000);
    const keepAlive = window.setInterval(() => {
      if (Date.now() - lastActivity.current < 10 * 60_000) refreshSession();
    }, 10 * 60_000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, mark));
      window.clearInterval(timer);
      window.clearInterval(keepAlive);
    };
  }, [me, logout]);

  const login = useCallback(
    async (email: string, password: string) => {
      const data = await api<{ access_token: string }>("/auth/login", { method: "POST", body: { email, password } });
      setAccessToken(data.access_token);
      setNotice(null);
      lastActivity.current = Date.now();
      await loadMe();
    },
    [loadMe],
  );

  const value = useMemo<AuthState>(() => {
    const perms = new Set(me?.permissions || []);
    return {
      me,
      loading,
      notice,
      login,
      logout,
      reload: loadMe,
      can: (...p) => p.every((x) => perms.has(x)),
      canAny: (...p) => p.some((x) => perms.has(x)),
    };
  }, [me, loading, notice, login, logout, loadMe]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth fora do AuthProvider");
  return v;
}
