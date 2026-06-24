import { FunctionComponent, useMemo } from "react";
import { Link } from "react-router";
import { Anchor, Badge, Group } from "@mantine/core";
import { faFileLines, faSearch } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { ColumnDef } from "@tanstack/react-table";
import {
  useMovieAction,
  useMovieSubtitleModification,
  useMovieWantedPagination,
} from "@/apis/hooks";
import Language from "@/components/bazarr/Language";
import TextPopover from "@/components/TextPopover";
import WantedView from "@/pages/views/WantedView";
import { BuildKey } from "@/utilities";

const WantedMoviesView: FunctionComponent = () => {
  const { download } = useMovieSubtitleModification();

  const columns = useMemo<ColumnDef<Wanted.Movie>[]>(
    () => [
      {
        header: "Name",
        accessorKey: "title",
        cell: ({
          row: {
            original: { title, radarrId },
          },
        }) => {
          const target = `/movies/${radarrId}`;
          return (
            <Anchor component={Link} to={target}>
              {title}
            </Anchor>
          );
        },
      },
      {
        header: "Path",
        accessorKey: "path",
        cell: ({
          row: {
            original: { path, pathShort },
          },
        }) => {
          return (
            <TextPopover text={path}>
              <span>{pathShort}</span>
            </TextPopover>
          );
        },
      },
      {
        header: "Release",
        accessorKey: "sceneName",
        cell: ({
          row: {
            original: { sceneName },
          },
        }) => {
          return (
            <TextPopover text={sceneName}>
              <FontAwesomeIcon size="2x" icon={faFileLines}></FontAwesomeIcon>
            </TextPopover>
          );
        },
      },
      {
        header: "Missing",
        accessorKey: "missing_subtitles",
        cell: ({
          row: {
            original: { radarrId, missing_subtitles: missingSubtitles },
          },
        }) => {
          return (
            <Group gap="sm">
              {missingSubtitles.map((item, idx) => (
                <Badge
                  color={download.isPending ? "gray" : undefined}
                  leftSection={<FontAwesomeIcon icon={faSearch} />}
                  key={BuildKey(idx, item.code2)}
                  style={{ cursor: "pointer" }}
                  onClick={async () => {
                    await download.mutateAsync({
                      radarrId,
                      form: {
                        language: item.code2,
                        hi: item.hi,
                        forced: item.forced,
                      },
                    });
                  }}
                >
                  <Language.Text value={item}></Language.Text>
                </Badge>
              ))}
            </Group>
          );
        },
      },
    ],
    [download],
  );

  const { mutateAsync } = useMovieAction();
  const query = useMovieWantedPagination();

  return (
    <WantedView
      name="Movies"
      columns={columns}
      query={query}
      searchAll={() => mutateAsync({ action: "search-wanted" })}
    ></WantedView>
  );
};

export default WantedMoviesView;
