import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST() {
  return NextResponse.json({
    ok: true,
    message: "Runtime cleanup is handled by the Python engine / SQLite instance.",
  });
}
