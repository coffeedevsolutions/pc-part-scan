import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";

const allowed = new Set(
  (process.env.ALLOWED_EMAILS ?? "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean),
);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [GitHub],
  callbacks: {
    signIn({ user, profile }) {
      const email = (user.email ?? (profile?.email as string | undefined) ?? "")
        .toLowerCase();
      return allowed.has(email);
    },
    authorized({ auth }) {
      return !!auth?.user;
    },
  },
});
