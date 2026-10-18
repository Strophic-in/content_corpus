import { Bone, Head, VideoGridSkeleton } from "../skeletons";

export default function Loading() {
  return (
    <div role="status" aria-label="Loading" className="mx-auto flex w-full max-w-5xl flex-col gap-5">
      <Head />
      <Bone className="h-16 w-full rounded-2xl" />
      <VideoGridSkeleton />
    </div>
  );
}
