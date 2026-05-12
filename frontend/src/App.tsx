import { useEffect, useState } from "react";
import { ApiError, clearToken, fetchMe, getStoredToken, getStoredUser, storeToken, storeUser, type User } from "./api";
import { Dashboard } from "./Dashboard";
import { LoginPage } from "./LoginPage";

type AuthState =
  | { status: "loading"; token: string | null; user: null }
  | { status: "anonymous"; token: null; user: null }
  | { status: "authenticated"; token: string; user: User };

export function App() {
  const [auth, setAuth] = useState<AuthState>({ status: "loading", token: null, user: null });

  useEffect(() => {
    const token = getStoredToken();
    const storedUser = getStoredUser();
    if (!token) {
      setAuth({ status: "anonymous", token: null, user: null });
      return;
    }
    if (storedUser) {
      setAuth({ status: "authenticated", token, user: storedUser });
    }
    fetchMe(token)
      .then((user) => {
        storeUser(user);
        setAuth({ status: "authenticated", token, user });
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          clearToken();
          setAuth({ status: "anonymous", token: null, user: null });
          return;
        }
        if (!storedUser) {
          setAuth({ status: "anonymous", token: null, user: null });
        }
      });
  }, []);

  if (auth.status === "loading") {
    return <div className="boot-screen">Loading...</div>;
  }

  if (auth.status === "anonymous") {
    return (
      <LoginPage
        onAuthenticated={(token, user) => {
          storeToken(token);
          storeUser(user);
          setAuth({ status: "authenticated", token, user });
        }}
      />
    );
  }

  return (
    <Dashboard
      token={auth.token}
      user={auth.user}
      onLogout={() => {
        clearToken();
        setAuth({ status: "anonymous", token: null, user: null });
      }}
    />
  );
}
