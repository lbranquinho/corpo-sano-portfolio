import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { get } from "./api";
import { useToast } from "../components/ui";

export function useGet<T = any>(key: QueryKey, path: string | null, params?: Record<string, unknown>, enabled = true) {
  return useQuery<T>({
    queryKey: [...(Array.isArray(key) ? key : [key]), params],
    queryFn: () => get<T>(path as string, params),
    enabled: enabled && !!path,
  });
}

/** Mutação com mensagem de sucesso/erro e invalidação de cache. */
export function useAction<V = any, R = any>(fn: (v: V) => Promise<R>, opts: { success?: string | ((r: R) => string); invalidate?: QueryKey[]; onDone?: (r: R) => void } = {}) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation<R, Error, V>({
    mutationFn: fn,
    onSuccess: (r) => {
      const msg = typeof opts.success === "function" ? opts.success(r) : opts.success ?? (r as any)?.message;
      if (msg) toast.success(msg);
      (opts.invalidate || []).forEach((k) => qc.invalidateQueries({ queryKey: k }));
      opts.onDone?.(r);
    },
    onError: (e) => toast.error(e),
  });
}

export function useLookups() {
  const professionals = useGet<any[]>(["professionals"], "/settings/professionals", { active: true });
  const rooms = useGet<any[]>(["rooms"], "/settings/rooms", { active: true });
  const services = useGet<any[]>(["services"], "/services", { active: true });
  const methods = useGet<any[]>(["payment-methods"], "/settings/payment-methods", { active: true });
  return {
    professionals: professionals.data || [],
    rooms: rooms.data || [],
    services: services.data || [],
    methods: methods.data || [],
  };
}
