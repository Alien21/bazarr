import {
  useEpisodeSubtitleModification,
  useEpisodeWantedPagination,
  useSeriesAction,
} from "@/apis/hooks";
import TextPopover from "@/components/TextPopover";
import Language from "@/components/bazarr/Language";
import { TaskGroup, task } from "@/modules/task";
import WantedView from "@/pages/views/WantedView";
import { useTableStyles } from "@/styles";
import { BuildKey } from "@/utilities";
import { faFileLines, faSearch } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { Anchor, Badge, Group, Text } from "@mantine/core";
import { FunctionComponent, useMemo } from "react";
import { Link } from "react-router-dom";
import { Column } from "react-table";

const WantedSeriesView: FunctionComponent = () => {
  const columns: Column<Wanted.Episode>[] = useMemo<Column<Wanted.Episode>[]>(
    () => [
      {
        Header: "Name",
        accessor: "seriesTitle",
        Cell: (row) => {
          const target = `/series/${row.row.original.sonarrSeriesId}`;
          const { classes } = useTableStyles();
          return (
            <Anchor className={classes.primary} component={Link} to={target}>
              {row.value}
            </Anchor>
          );
        },
      },
      {
        Header: "Episode",
        accessor: "episode_number",
      },
      {
        accessor: "episodeTitle",
        Cell: ({ value }) => {
          const { classes } = useTableStyles();

          return <Text className={classes.noWrap}>{value}</Text>;
        },
      },

      {
        Header: "Path",
        accessor: "path",
        Cell: ({ value }) => {
          const { classes } = useTableStyles();
          return <Text className={classes.width7em}>{value}</Text>;
        },
      },
      {
        Header: "Release",
        accessor: "sceneName",
        className: "width6em text-center",
        Cell: ({ row }) => {
          return (
            <TextPopover text={row.original.sceneName}>
              <FontAwesomeIcon size="2x" icon={faFileLines}></FontAwesomeIcon>
            </TextPopover>
          );
        },
      },

      {
        Header: "Missing",
        accessor: "missing_subtitles",
        Cell: ({ row, value }) => {
          const wanted = row.original;
          const seriesId = wanted.sonarrSeriesId;
          const episodeId = wanted.sonarrEpisodeId;

          const { download } = useEpisodeSubtitleModification();

          return (
            <Group spacing="sm">
              {value.map((item, idx) => (
                <Badge
                  color={download.isLoading ? "gray" : undefined}
                  leftSection={<FontAwesomeIcon icon={faSearch} />}
                  key={BuildKey(idx, item.code2)}
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    task.create(
                      item.name,
                      TaskGroup.SearchSubtitle,
                      download.mutateAsync,
                      {
                        seriesId,
                        episodeId,
                        form: {
                          language: item.code2,
                          hi: item.hi,
                          forced: item.forced,
                        },
                      }
                    );
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
    []
  );

  const { mutateAsync } = useSeriesAction();
  const query = useEpisodeWantedPagination();
  return (
    <WantedView
      name="Series"
      columns={columns}
      query={query}
      searchAll={() => mutateAsync({ action: "search-wanted" })}
    ></WantedView>
  );
};

export default WantedSeriesView;
