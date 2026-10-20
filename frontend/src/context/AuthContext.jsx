import { createContext, useContext, useEffect, useState } from "react";
import api from "../lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);

  useEffect(() => {
    api.get("/auth/me")
      .then(({ data }) => setUser(data))
      .catch(() => setUser(false));
  }, []);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    if (data?.token && typeof window !== "undefined") {
      localStorage.setItem("admin_token", data.token);
    }
    setUser(data);
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      if (typeof window !== "undefined") {
        localStorage.removeItem("admin_token");
      }
      setUser(false);
    }
  };

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
